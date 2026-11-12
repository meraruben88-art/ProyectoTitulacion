"""El PIS dentro del agente: propuesta con RAG, edición libre del docente y criterios de la guía.

El PIS va aparte de las secciones del sílabo: no detiene el flujo ni pasa por la aprobación
sección a sección. El agente lo propone a partir de la Guía de construcción de PIS (recuperada
del corpus), de la ficha curricular de este PF y de los PF del mismo nivel de la malla —que son
los candidatos a participar—, y el docente lo cambia cuando quiera: entero, por partes o
pidiéndole al agente que rehaga una parte con una indicación.

El flujo es un grafo de LangGraph sin pausas: contexto -> recuperar -> redactar -> validar.
"""

import json
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from syllabusai.agent.harness import ErrorHarness, Harness
from syllabusai.config import Config
from syllabusai.db.modelos import Asignatura, Documento, ProyectoIntegrador, Silabo, TipoDocumento
from syllabusai.ingest.catalogo import ficha_de
from syllabusai.llm.base import ClienteLLM
from syllabusai.pis.esquemas import (
    ETAPAS,
    EVALUACION_GUIA,
    PREGUNTAS_REFLEXION,
    ROLES_GUIA,
    SalidaPIS,
    pis_vacio,
)
from syllabusai.pis.esquemas import ProyectoIntegrador as EsquemaPIS
from syllabusai.retrieval.recuperador import Recuperador
from syllabusai.telemetry.eventos import registrar

HERRAMIENTAS = ("consultar_guia_pis", "identificar_competencias", "listar_pf_del_nivel")
CONSULTAS = (
    "formulación del problema del territorio PIS pregunta de actuación delimitación",
    "matriz de articulación competencias PF RAP aporte al PIS momento evidencia parcial",
    "prueba de interdisciplinariedad evidencia integradora criterios de logro socialización",
    "diseño de la investigación secuencia de la actuación etapas cronograma",
    "errores que deben evitarse criterios de validación del PIS",
)
PARTES = tuple(EsquemaPIS.model_fields)

SISTEMA = """Eres SyllabusAI y ayudas a un docente de la Universidad Tecnológica Indoamérica a \
construir el PIS (Proyecto Interdisciplinario Socioformativo) en el que participa su Proyecto \
Formativo, siguiendo la Guía metodológica de construcción de PIS.

Reglas:
1. El PIS parte de un problema real del territorio, no de la necesidad de agrupar PF. No inventes \
datos, cifras ni actores: usa el contexto que dio el docente; si falta, deja el campo vacío y dilo \
en "notas".
2. En la matriz de articulación usa SOLO los RAP existentes que se te entregan (los de este PF y \
los de los PF del mismo nivel). No crees resultados nuevos ni los reescribas.
3. Incluye solo los PF cuyo aporte sea indispensable (prueba de interdisciplinariedad).
4. El propósito sigue la plantilla «Diseñar / analizar / desarrollar / validar ___ para ___, \
considerando ___».
5. Todas las evidencias parciales confluyen en una sola evidencia integradora; las etapas dependen \
unas de otras.
6. En "fuentes" pon los [id] de los fragmentos de la guía que usaste.
7. Si el docente pide cambiar solo una parte, cambia solo esa parte y conserva el resto.
8. Responde solo con un objeto JSON que cumpla el esquema."""


class ErrorPIS(ValueError):
    pass


class EstadoPIS(TypedDict, total=False):
    silabo_id: int
    indicacion: str | None
    parte: str | None
    contexto: dict[str, Any]
    fragmentos: list[dict[str, Any]]
    salida: dict[str, Any]
    notas: str | None
    fuentes: list[str]
    metricas: dict[str, Any]


class ServicioPIS:
    def __init__(self, fabrica: sessionmaker[Session], recuperador: Recuperador, llm: ClienteLLM,
                 config: Config):
        self.fabrica = fabrica
        self.recuperador = recuperador
        self.llm = llm
        self.config = config
        self.grafo = self._construir_grafo().compile()

    @property
    def harness(self) -> Harness:
        return Harness(self.llm)

    # --- consultas -----------------------------------------------------------------------

    def _registro(self, sesion: Session, silabo_id: int) -> ProyectoIntegrador:
        pis = sesion.scalar(select(ProyectoIntegrador).where(ProyectoIntegrador.silabo_id == silabo_id))
        if pis is None:
            if sesion.get(Silabo, silabo_id) is None:
                raise ErrorPIS(f"No existe el sílabo {silabo_id}")
            pis = ProyectoIntegrador(silabo_id=silabo_id, contenido=pis_vacio(), historial=[],
                                     citas=[], hallazgos=[])
            sesion.add(pis)
            sesion.flush()
        return pis

    def obtener(self, silabo_id: int) -> dict:
        with self.fabrica() as sesion:
            pis = self._registro(sesion, silabo_id)
            sesion.commit()
            contenido = EsquemaPIS.model_validate(pis.contenido or {}).model_dump(mode="json")
            return {"silabo_id": silabo_id, "estado": pis.estado, "contenido": contenido,
                    "historial": pis.historial, "citas": pis.citas,
                    "criterios": criterios(contenido), "actualizado": pis.actualizado.isoformat(),
                    "partes": list(PARTES)}

    # --- grafo ---------------------------------------------------------------------------

    def _construir_grafo(self) -> StateGraph:
        def contexto(estado: EstadoPIS) -> dict:
            return {"contexto": self._contexto(estado["silabo_id"])}

        def recuperar(estado: EstadoPIS) -> dict:
            ctx = estado["contexto"]
            tarea = self.harness.tarea("pis", HERRAMIENTAS)
            vistos: dict[str, Any] = {}
            for consulta in CONSULTAS:
                for r in tarea.usar("consultar_guia_pis", self.recuperador.buscar, consulta,
                                    tipos=[TipoDocumento.NORMATIVA, TipoDocumento.PLANTILLA],
                                    carrera=ctx["asignatura"]["carrera"], k=3):
                    vistos.setdefault(r.fragmento.fragmento_id, r)
            for r in tarea.usar("identificar_competencias", self.recuperador.buscar,
                                f"competencias perfil de egreso {ctx['asignatura']['carrera']}",
                                tipos=[TipoDocumento.PERFIL_EGRESO],
                                carrera=ctx["asignatura"]["carrera"], k=3):
                vistos.setdefault(r.fragmento.fragmento_id, r)
            fragmentos = [
                {"id": r.fragmento.fragmento_id, "titulo": r.fragmento.titulo,
                 "version": r.fragmento.version, "pagina": r.fragmento.pagina_inicio,
                 "documento_id": r.fragmento.documento_id, "texto": r.fragmento.texto}
                for r in list(vistos.values())[:12]
            ]
            return {"fragmentos": fragmentos}

        def redactar(estado: EstadoPIS) -> dict:
            ctx = estado["contexto"] | {"fragmentos": estado["fragmentos"],
                                        "indicacion": estado.get("indicacion"),
                                        "parte": estado.get("parte")}
            try:
                resultado = self.harness.generar(
                    "pis", _mensajes(ctx), SalidaPIS, contexto=ctx,
                    fragmentos_validos=[f["id"] for f in estado["fragmentos"]],
                )
            except ErrorHarness as error:
                raise ErrorPIS(str(error)) from error
            nuevo = resultado.salida.contenido.model_dump(mode="json")
            parte = estado.get("parte")
            if parte:  # solo cambia la parte pedida; el resto queda como estaba
                nuevo = ctx["actual"] | {parte: nuevo[parte]}
            return {"salida": nuevo, "notas": resultado.salida.notas or resultado.salida.abstencion,
                    "fuentes": resultado.citas_validas, "metricas": resultado.metricas()}

        grafo = StateGraph(EstadoPIS)
        grafo.add_node("contexto", contexto)
        grafo.add_node("recuperar", recuperar)
        grafo.add_node("redactar", redactar)
        grafo.add_edge(START, "contexto")
        grafo.add_edge("contexto", "recuperar")
        grafo.add_edge("recuperar", "redactar")
        grafo.add_edge("redactar", END)
        return grafo

    def _contexto(self, silabo_id: int) -> dict[str, Any]:
        with self.fabrica() as sesion:
            silabo = sesion.get(Silabo, silabo_id)
            if silabo is None:
                raise ErrorPIS(f"No existe el sílabo {silabo_id}")
            a = silabo.asignatura
            ficha = ficha_de(a)
            # PF del mismo nivel y carrera: los candidatos a articularse en el PIS del periodo.
            companeras = []
            for otra in sesion.scalars(select(Asignatura).where(
                Asignatura.carrera == a.carrera, Asignatura.nivel == a.nivel, Asignatura.id != a.id,
            ).order_by(Asignatura.codigo)):
                try:
                    f = ficha_de(otra)
                except ValidationError:
                    continue
                companeras.append({"codigo": otra.codigo, "nombre": otra.nombre,
                                   "resultados": [r.model_dump() for r in f.resultados_aprendizaje]})
            pis = self._registro(sesion, silabo_id)
            sesion.commit()
            datos = {k: v for k, v in silabo.datos_generales.items()
                     if k not in ("preferencias", "interpretacion_inicial", "pis")}
            return {
                "asignatura": {"codigo": a.codigo, "nombre": a.nombre, "carrera": a.carrera,
                               "nivel": a.nivel},
                "periodo": silabo.periodo,
                "docente": silabo.docente.nombre,
                "ficha": ficha.model_dump(mode="json"),
                "companeras": companeras,
                "datos_generales": datos,
                "preferencias": silabo.datos_generales.get("preferencias") or {},
                "actual": EsquemaPIS.model_validate(pis.contenido or {}).model_dump(mode="json"),
                "etapas": list(ETAPAS),
                "roles": [r.model_dump() for r in ROLES_GUIA],
                "evaluacion": EVALUACION_GUIA,
                "reflexion": PREGUNTAS_REFLEXION,
            }

    # --- operaciones ---------------------------------------------------------------------

    def generar(self, silabo_id: int, indicacion: str | None = None, parte: str | None = None) -> dict:
        if parte and parte not in PARTES:
            raise ErrorPIS(f"El PIS no tiene la parte «{parte}»")
        estado = self.grafo.invoke({"silabo_id": silabo_id, "indicacion": indicacion, "parte": parte})
        with self.fabrica() as sesion:
            pis = self._registro(sesion, silabo_id)
            pis.contenido = estado["salida"]
            pis.estado = "propuesto"
            por_id = {f["id"]: f for f in estado["fragmentos"]}
            documentos = {d.id: d for d in sesion.scalars(select(Documento))}
            pis.citas = [
                {"fragmento_id": fid, "documento": por_id[fid]["titulo"],
                 "version": por_id[fid]["version"], "pagina": por_id[fid]["pagina"],
                 "vigente": str(documentos[por_id[fid]["documento_id"]].estado) == "vigente"
                 if por_id[fid]["documento_id"] in documentos else False,
                 "texto": por_id[fid]["texto"][:1200]}
                for fid in estado["fuentes"] if fid in por_id
            ]
            pis.historial = [*pis.historial, {
                "n": len(pis.historial) + 1, "origen": "agente", "indicacion": indicacion,
                "parte": parte, "nota": estado.get("notas"), "fecha": datetime.now(UTC).isoformat(),
            }]
            self._sincronizar_silabo(sesion, silabo_id, estado["salida"])
            m = estado.get("metricas", {})
            registrar(sesion, "generacion", silabo_id=silabo_id, paso="pis",
                      latencia_ms=m.get("latencia_ms"), ttft_ms=m.get("ttft_ms"),
                      tokens_in=m.get("tokens_in"), tokens_out=m.get("tokens_out"),
                      payload={"parte": parte, "indicacion": indicacion, "fragmentos": len(por_id),
                               "intentos": m.get("intentos"), "herramientas": m.get("herramientas")})
            sesion.commit()
        return self.obtener(silabo_id)

    def guardar(self, silabo_id: int, contenido: dict) -> dict:
        try:
            limpio = EsquemaPIS.model_validate(contenido).model_dump(mode="json")
        except ValidationError as error:
            raise ErrorPIS(f"El PIS no cumple el esquema: {error}") from error
        with self.fabrica() as sesion:
            pis = self._registro(sesion, silabo_id)
            pis.contenido = limpio
            pis.estado = "editado"
            pis.historial = [*pis.historial, {
                "n": len(pis.historial) + 1, "origen": "docente", "indicacion": None, "parte": None,
                "nota": "Edición del docente", "fecha": datetime.now(UTC).isoformat(),
            }]
            self._sincronizar_silabo(sesion, silabo_id, limpio)
            registrar(sesion, "correccion", silabo_id=silabo_id, paso="pis", payload={})
            sesion.commit()
        return self.obtener(silabo_id)

    @staticmethod
    def _sincronizar_silabo(sesion: Session, silabo_id: int, contenido: dict) -> None:
        """El sílabo recuerda el PIS: la sección 7.2 declara su aporte al PIS sin horas extra."""
        silabo = sesion.get(Silabo, silabo_id)
        datos = dict(silabo.datos_generales)
        datos["pis"] = {"titulo": contenido.get("titulo"), "aporte": contenido.get("aporte_este_pf"),
                        "evidencia_integradora": contenido.get("evidencia_integradora")}
        if contenido.get("titulo"):
            datos["pis_periodo"] = contenido["titulo"]
        silabo.datos_generales = datos


def _mensajes(ctx: dict) -> list[dict[str, str]]:
    def j(datos) -> str:
        return json.dumps(datos, ensure_ascii=False, indent=2)

    a = ctx["asignatura"]
    partes = [
        (f"Proyecto Formativo del docente: {a['nombre']} ({a['codigo']}), carrera {a['carrera']}, "
         f"nivel {a['nivel']}, periodo {ctx['periodo']}. Docente: {ctx['docente']}."),
        f"Resultados de aprendizaje oficiales de este PF:\n{j(ctx['ficha']['resultados_aprendizaje'])}",
        f"Competencia del perfil (si la ficha la trae): {ctx['ficha'].get('competencia_especifica') or '—'}",
        "PF del mismo nivel y carrera, con sus RAP oficiales (candidatos a articularse):\n"
        + j(ctx["companeras"]),
        f"Contexto del problema que dio el docente:\n{j(ctx['datos_generales'])}",
        f"Preferencias del docente:\n{j(ctx['preferencias'])}",
        "Etapas de la actuación (guía 7.5): " + ", ".join(ctx["etapas"]),
        f"Evaluación institucional (guía 7.8): {ctx['evaluacion']}",
    ]
    if any(v for v in ctx["actual"].values()):
        partes.append(f"PIS actual (consérvalo salvo lo que se pida cambiar):\n{j(ctx['actual'])}")
    if ctx.get("parte"):
        partes.append(f"Cambia SOLO la parte «{ctx['parte']}» del PIS.")
    if ctx.get("indicacion"):
        partes.append(f"Indicación del docente: {ctx['indicacion']}")
    fragmentos = "\n\n".join(
        f"[{f['id']}] {f['titulo']} (versión {f['version']}, p. {f['pagina']})\n{f['texto']}"
        for f in ctx["fragmentos"]
    ) or "(no se recuperaron fragmentos de la guía)"
    partes.append(f"Fragmentos de la guía y del perfil:\n{fragmentos}")
    partes.append('Devuelve {"contenido": {...}, "fuentes": ["id", ...], "abstencion": null, "notas": "..."}.')
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": "\n\n".join(partes)}]


def criterios(contenido: dict) -> list[dict]:
    """Criterios de validación del PIS (sección 9 de la guía) sobre los datos del PIS."""
    c = EsquemaPIS.model_validate(contenido)
    pf = {f.pf.strip() for f in c.articulacion if f.pf.strip()}
    proposito = c.proposito.strip().lower()

    def item(criterio: str, cumple: bool, detalle: str = "") -> dict:
        return {"criterio": criterio, "cumple": cumple, "detalle": "" if cumple else detalle}

    return [
        item("El problema es real, pertinente, delimitado y abordable.",
             bool(c.problema.strip() and c.contexto.strip() and c.delimitacion.strip()),
             "Complete el problema, el contexto o territorio y la delimitación."),
        item("El problema requiere aportes de más de un campo disciplinar.", len(pf) >= 2,
             "La matriz de articulación debe tener al menos dos PF distintos."),
        item("El propósito expresa una actuación interdisciplinaria.",
             proposito.startswith(("diseñar", "analizar", "desarrollar", "validar", "implementar",
                                   "evaluar", "proponer", "construir")) and "para" in proposito,
             "Use la plantilla «Diseñar / analizar / desarrollar / validar ___ para ___, considerando ___»."),
        item("Las competencias seleccionadas guardan relación con el problema.", bool(c.competencias),
             "Declare las competencias del perfil que moviliza el problema."),
        item("Cada PF participante tiene un aporte sustantivo y justificado.",
             bool(c.articulacion) and all(f.aporte.strip() and f.evidencia_parcial.strip() for f in c.articulacion),
             "Cada fila de la matriz necesita su aporte y su evidencia parcial."),
        item("Los RAP seleccionados están directamente relacionados con la actuación.",
             bool(c.articulacion) and all(f.rap.strip() for f in c.articulacion),
             "Indique el RAP existente de cada PF en la matriz."),
        item("El proyecto se sustenta en un proceso de investigación.",
             bool(c.investigacion.pregunta.strip() and c.investigacion.enfoque.strip()),
             "Defina la pregunta de indagación y el enfoque o método."),
        item("Existe articulación temporal y lógica entre los aportes.",
             len(c.etapas) >= 3 and all(e.resultado.strip() for e in c.etapas),
             "Encadene las etapas: el resultado de cada una alimenta la siguiente."),
        item("Existe una evidencia integradora.", bool(c.evidencia_integradora.strip()),
             "Defina la evidencia final en que confluyen los aportes."),
        item("Las actividades y el cronograma son viables.", len(c.cronograma) >= 3,
             "Distribuya al menos tres actividades en las semanas del periodo."),
        item("Se han definido criterios de evaluación en la escala institucional.",
             bool(c.evaluacion.strip() and c.criterios_logro),
             "Indique la evaluación y los criterios de logro de la evidencia."),
        item("Se contempla reflexión y mejora.", bool(c.reflexion),
             "Incluya las preguntas de reflexión del cierre."),
        item("Se han definido responsables y recursos.", bool(c.roles and c.recursos.strip()),
             "Complete los roles y los recursos y condiciones."),
        item("Se registró la prueba de interdisciplinariedad (sección 10).",
             bool(c.prueba_interdisciplinariedad.strip()),
             "Responda si el problema podría resolverse igual eliminando uno de los PF."),
    ]
