"""Noticias para los docentes, redactadas por el agente a partir del corpus (RAG).

Cada vez que algo cambia —se publica una versión nueva del formato de sílabo o de una normativa,
llega una malla, una fuente externa cambia o el administrador escribe un aviso— el agente redacta
una noticia corta. La redacción es aumentada por recuperación: se comparan los fragmentos de la
versión nueva con los de la anterior, se recuperan los relevantes del índice y el modelo resume
solo lo que dicen esos fragmentos, con sus citas. Además se cuenta qué sílabos en elaboración
citaban la versión anterior, para que sus docentes sepan qué revisar.

El flujo es un grafo de LangGraph: evento -> recuperar -> redactar -> publicar.
"""

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from syllabusai.agent.harness import ErrorHarness, Harness
from syllabusai.db.modelos import (
    Cita,
    Documento,
    EstadoDocumento,
    EstadoSilabo,
    Noticia,
    Seccion,
    Silabo,
    TipoDocumento,
    VersionSeccion,
)
from syllabusai.esquemas import PayloadFragmento
from syllabusai.llm.base import ClienteLLM
from syllabusai.retrieval.lexico import normalizar
from syllabusai.retrieval.recuperador import Recuperador
from syllabusai.telemetry.eventos import registrar

# Secciones del sílabo a las que afecta cada tipo de documento.
SECCIONES_POR_TIPO = {
    TipoDocumento.PLANTILLA: ["todas (formato del sílabo)"],
    TipoDocumento.NORMATIVA: ["7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "9"],
    TipoDocumento.PERFIL_EGRESO: ["7.2 Anclaje curricular"],
    TipoDocumento.MALLA: ["7.1 Información general", "7.4 Resultados de aprendizaje", "7.5 Contenidos"],
    TipoDocumento.CONTENIDOS_MINIMOS: ["7.5 Contenidos"],
    TipoDocumento.SILABO_APROBADO: ["7.6 Planeación (como referencia de estilo)"],
}
CATEGORIA_POR_TIPO = {
    TipoDocumento.PLANTILLA: "silabo", TipoDocumento.NORMATIVA: "normativa",
    TipoDocumento.PERFIL_EGRESO: "documento", TipoDocumento.MALLA: "malla",
    TipoDocumento.CONTENIDOS_MINIMOS: "malla", TipoDocumento.SILABO_APROBADO: "documento",
}

SISTEMA = """Eres SyllabusAI y redactas noticias breves para los docentes de la Universidad \
Tecnológica Indoamérica sobre cambios en los documentos que rigen la elaboración de sílabos.

Reglas:
1. Usa SOLO lo que dicen el evento y los fragmentos entregados. No inventes fechas, cifras ni \
cambios.
2. El título tiene a lo sumo 90 caracteres y dice qué cambió. El resumen tiene dos o tres frases \
y explica qué debe hacer el docente.
3. En "puntos" pon entre dos y cinco cambios concretos, cada uno sustentado en un fragmento.
4. En "fuentes" pon los [id] de los fragmentos que usaste.
5. Responde solo con un objeto JSON que cumpla el esquema."""

SISTEMA_PREGUNTA = """Eres SyllabusAI. Respondes preguntas de los docentes sobre la normativa, el \
formato del sílabo, las mallas y las novedades, usando SOLO los fragmentos entregados (documentos \
vigentes). Si no alcanzan, no respondas: explica en "abstencion" qué falta. Cita los [id] usados \
en "fuentes". Responde solo con un objeto JSON."""


class ContenidoNoticia(BaseModel):
    titulo: str
    resumen: str
    puntos: list[str] = []
    secciones_afectadas: list[str] = []


class SalidaNoticia(BaseModel):
    contenido: ContenidoNoticia
    fuentes: list[str] = []
    abstencion: str | None = None
    notas: str | None = None


class ContenidoRespuesta(BaseModel):
    respuesta: str = ""
    puntos: list[str] = []


class SalidaRespuesta(BaseModel):
    contenido: ContenidoRespuesta
    fuentes: list[str] = []
    abstencion: str | None = None
    notas: str | None = None


class EstadoNoticia(TypedDict, total=False):
    evento: dict[str, Any]
    fragmentos: list[dict[str, Any]]
    noticia: dict[str, Any]
    fuentes: list[str]
    noticia_id: int


def _como_prompt(f: PayloadFragmento) -> dict[str, Any]:
    return {"id": f.fragmento_id, "titulo": f.titulo, "version": f.version,
            "pagina": f.pagina_inicio, "texto": f.texto, "tipo": str(f.tipo_documento)}


def _clave_texto(texto: str) -> str:
    return " ".join(normalizar(texto).split())[:400]


class ServicioNoticias:
    def __init__(self, fabrica: sessionmaker[Session], recuperador: Recuperador, llm: ClienteLLM):
        self.fabrica = fabrica
        self.recuperador = recuperador
        self.llm = llm
        self.grafo = self._construir_grafo().compile()
        # Quien sigue las noticias en vivo (la web refresca el panel al recibir una).
        self.oyentes: list = []

    @property
    def harness(self) -> Harness:
        return Harness(self.llm)

    # --- grafo ---------------------------------------------------------------------------

    def _construir_grafo(self) -> StateGraph:
        def recuperar(estado: EstadoNoticia) -> dict:
            evento = estado["evento"]
            fragmentos = list(evento.get("fragmentos_evento") or [])
            if evento.get("consulta"):
                tarea = self.harness.tarea("noticia", ["consultar_corpus"])
                for r in tarea.usar("consultar_corpus", self.recuperador.buscar, evento["consulta"],
                                    carrera=evento.get("carrera"), k=4):
                    fragmentos.append(_como_prompt(r.fragmento))
            vistos, unicos = set(), []
            for f in fragmentos:
                if f["id"] not in vistos:
                    vistos.add(f["id"])
                    unicos.append(f)
            return {"fragmentos": unicos[:10]}

        def redactar(estado: EstadoNoticia) -> dict:
            evento, fragmentos = estado["evento"], estado["fragmentos"]
            ctx = {"evento": evento, "fragmentos": fragmentos}
            try:
                r = self.harness.generar("noticia", _mensajes(evento, fragmentos), SalidaNoticia,
                                         contexto=ctx, fragmentos_validos=[f["id"] for f in fragmentos])
                noticia = r.salida.contenido.model_dump()
                fuentes = r.citas_validas
            except ErrorHarness:
                # Sin modelo disponible la noticia sale igual, con la descripción del evento.
                noticia = {"titulo": evento["titulo"], "resumen": evento["descripcion"], "puntos": [],
                           "secciones_afectadas": evento.get("secciones_afectadas", [])}
                fuentes = []
            if not noticia.get("secciones_afectadas"):
                noticia["secciones_afectadas"] = evento.get("secciones_afectadas", [])
            return {"noticia": noticia, "fuentes": fuentes}

        def publicar(estado: EstadoNoticia) -> dict:
            evento, n = estado["evento"], estado["noticia"]
            por_id = {f["id"]: f for f in estado["fragmentos"]}
            puntos = list(n.get("puntos") or [])
            if n.get("secciones_afectadas"):
                puntos.append("Secciones del sílabo que conviene revisar: "
                              + ", ".join(n["secciones_afectadas"]) + ".")
            if evento.get("silabos_afectados"):
                puntos.append(f"{evento['silabos_afectados']} sílabo(s) en elaboración citan la versión "
                              "anterior: sus docentes deberían regenerar o revisar esas secciones.")
            with self.fabrica() as sesion:
                noticia = Noticia(
                    titulo=n["titulo"][:300], resumen=n["resumen"], puntos=puntos,
                    categoria=evento["categoria"], origen=evento.get("origen", "automatica"),
                    carrera=evento.get("carrera") or "TODAS", importante=evento.get("importante", False),
                    documento_id=evento.get("documento_id"), fuente_url=evento.get("fuente_url"),
                    citas=[f"{por_id[i]['titulo']}, versión {por_id[i]['version']}, p. {por_id[i]['pagina']}"
                           for i in estado["fuentes"] if i in por_id],
                    autor_id=evento.get("autor_id"),
                )
                sesion.add(noticia)
                sesion.flush()
                registrar(sesion, "noticia", paso=evento["categoria"],
                          payload={"noticia_id": noticia.id, "fragmentos": len(por_id)})
                sesion.commit()
                datos = noticia_dict(noticia)
            for oyente in list(self.oyentes):
                oyente(datos)
            return {"noticia_id": datos["id"]}

        grafo = StateGraph(EstadoNoticia)
        grafo.add_node("recuperar", recuperar)
        grafo.add_node("redactar", redactar)
        grafo.add_node("publicar", publicar)
        grafo.add_edge(START, "recuperar")
        grafo.add_edge("recuperar", "redactar")
        grafo.add_edge("redactar", "publicar")
        grafo.add_edge("publicar", END)
        return grafo

    def _publicar(self, evento: dict[str, Any]) -> dict:
        estado = self.grafo.invoke({"evento": evento})
        with self.fabrica() as sesion:
            return noticia_dict(sesion.get(Noticia, estado["noticia_id"]))

    # --- eventos -------------------------------------------------------------------------

    def _fragmentos_de(self, documento_id: int) -> list[PayloadFragmento]:
        n = self.recuperador.almacen.contar(documento_id)
        ids = [f"d{documento_id}-f{i:04d}" for i in range(1, n + 1)]
        return list(self.recuperador.almacen.obtener(ids).values()) if ids else []

    def documento_publicado(self, documento_id: int, autor_id: int | None = None) -> dict:
        """Noticia de un documento nuevo o de una versión nueva que reemplaza a otra."""
        with self.fabrica() as sesion:
            doc = sesion.get(Documento, documento_id)
            anteriores = [
                d for d in sesion.scalars(select(Documento).where(
                    Documento.tipo == doc.tipo, Documento.carrera == doc.carrera,
                    Documento.id != doc.id))
                if " ".join(d.titulo.split()).casefold() == " ".join(doc.titulo.split()).casefold()
            ]
            anterior = max(anteriores, key=lambda d: d.fecha_vigencia, default=None)
            afectados = 0
            if anterior is not None:
                afectados = len(set(sesion.scalars(
                    select(Silabo.id).join(Seccion).join(VersionSeccion).join(Cita)
                    .where(Cita.documento_id == anterior.id,
                           Silabo.estado.in_([EstadoSilabo.BORRADOR, EstadoSilabo.EN_REVISION,
                                              EstadoSilabo.APROBADO]))
                )))
            tipo, titulo, version = doc.tipo, doc.titulo, doc.version
            vigente = doc.estado == EstadoDocumento.VIGENTE
            fecha = doc.fecha_vigencia.strftime("%d/%m/%Y")
            ant = (anterior.id, anterior.version) if anterior else None
            carrera = doc.carrera

        nuevos = self._fragmentos_de(documento_id)
        if ant:
            viejos = {_clave_texto(f.texto) for f in self._fragmentos_de(ant[0])}
            cambiados = [f for f in nuevos if _clave_texto(f.texto) not in viejos]
            retirados = len(viejos - {_clave_texto(f.texto) for f in nuevos})
            descripcion = (f"Se publicó la versión {version} de «{titulo}», vigente desde {fecha}, "
                           f"que reemplaza a la versión {ant[1]}. Cambiaron {len(cambiados)} de "
                           f"{len(nuevos)} fragmentos y se retiraron {retirados}.")
            encabezado = f"Nueva versión de {titulo} ({version})"
        else:
            cambiados = nuevos
            descripcion = (f"Se incorporó «{titulo}» (versión {version}, vigente desde {fecha}) a los "
                           "documentos que usa el agente para elaborar sílabos.")
            encabezado = f"Nuevo documento: {titulo}"
        if not vigente:
            descripcion += " Entró como versión histórica: no se usa como evidencia."
        return self._publicar({
            "titulo": encabezado, "descripcion": descripcion,
            "categoria": CATEGORIA_POR_TIPO.get(tipo, "documento"), "carrera": carrera,
            "importante": tipo in (TipoDocumento.PLANTILLA, TipoDocumento.NORMATIVA) and ant is not None,
            "documento_id": documento_id, "autor_id": autor_id,
            "secciones_afectadas": SECCIONES_POR_TIPO.get(tipo, []),
            "silabos_afectados": afectados,
            "fragmentos_evento": [_como_prompt(f) for f in cambiados[:8]],
        })

    def documento_retirado(self, documento_id: int, autor_id: int | None = None) -> dict:
        with self.fabrica() as sesion:
            doc = sesion.get(Documento, documento_id)
            titulo, version, tipo, carrera = doc.titulo, doc.version, doc.tipo, doc.carrera
        return self._publicar({
            "titulo": f"{titulo} ({version}) deja de estar vigente",
            "descripcion": (f"La versión {version} de «{titulo}» se marcó como obsoleta: el agente ya no "
                            "la cita como evidencia. Las secciones que la citaban mostrarán una alerta."),
            "categoria": CATEGORIA_POR_TIPO.get(tipo, "documento"), "carrera": carrera,
            "documento_id": documento_id, "autor_id": autor_id,
            "secciones_afectadas": SECCIONES_POR_TIPO.get(tipo, []),
        })

    def malla_importada(self, nombre: str, carrera: str, asignaturas: int, documento_id: int | None,
                        avisos: list[str], autor_id: int | None = None) -> dict:
        descripcion = (f"Se cargó la malla del CES de {nombre}: {asignaturas} asignaturas con sus "
                       "resultados de aprendizaje, contenidos mínimos y horas, listas para elaborar "
                       "sílabos una vez que el administrador las revise.")
        if avisos:
            descripcion += " " + " ".join(avisos)
        fragmentos = [_como_prompt(f) for f in self._fragmentos_de(documento_id)[:4]] if documento_id else []
        return self._publicar({
            "titulo": f"Malla curricular de {nombre} disponible", "descripcion": descripcion,
            "categoria": "malla", "carrera": carrera, "documento_id": documento_id,
            "autor_id": autor_id, "secciones_afectadas": SECCIONES_POR_TIPO[TipoDocumento.MALLA],
            "fragmentos_evento": fragmentos,
        })

    def cambio_externo(self, fuente: str, titulo: str, texto: str, url: str, carrera: str = "TODAS") -> dict:
        """Una fuente externa publicó algo nuevo: se resume y se relaciona con el corpus."""
        fragmento = {"id": "externo-1", "titulo": fuente, "version": "web", "pagina": 1,
                     "texto": texto[:2000], "tipo": "externa"}
        return self._publicar({
            "titulo": titulo[:200], "descripcion": f"{fuente} publicó: {texto[:300].strip()}",
            "categoria": "externa", "origen": "externa", "carrera": carrera, "fuente_url": url,
            "fragmentos_evento": [fragmento], "consulta": f"{titulo} {texto[:200]}",
        })

    def publicar_manual(self, titulo: str, cuerpo: str, categoria: str, carrera: str,
                        importante: bool, autor_id: int) -> dict:
        """Aviso que escribe el administrador: se publica tal cual, sin pasar por el modelo."""
        with self.fabrica() as sesion:
            noticia = Noticia(titulo=titulo[:300], resumen=cuerpo, puntos=[], categoria=categoria,
                              origen="manual", carrera=carrera or "TODAS", importante=importante,
                              autor_id=autor_id, citas=[])
            sesion.add(noticia)
            sesion.commit()
            datos = noticia_dict(noticia)
        for oyente in list(self.oyentes):
            oyente(datos)
        return datos

    # --- consultas -----------------------------------------------------------------------

    def listar(self, carrera: str | None = None, limite: int = 40, despues_de: int | None = None) -> list[dict]:
        with self.fabrica() as sesion:
            consulta = select(Noticia).order_by(Noticia.fecha.desc(), Noticia.id.desc()).limit(limite)
            if carrera:
                consulta = consulta.where(Noticia.carrera.in_([carrera, "TODAS"]))
            if despues_de:
                consulta = consulta.where(Noticia.id > despues_de)
            return [noticia_dict(n) for n in sesion.scalars(consulta)]

    def eliminar(self, noticia_id: int) -> None:
        with self.fabrica() as sesion:
            noticia = sesion.get(Noticia, noticia_id)
            if noticia is not None:
                sesion.delete(noticia)
                sesion.commit()

    def preguntar(self, pregunta: str, carrera: str | None = None) -> dict:
        """Pregunta libre de un docente, respondida con RAG sobre los documentos vigentes."""
        tarea = self.harness.tarea("respuesta", ["consultar_corpus"])
        resultados = tarea.usar("consultar_corpus", self.recuperador.buscar, pregunta, carrera=carrera, k=6)
        fragmentos = [_como_prompt(r.fragmento) for r in resultados if r.puntaje_lexico > 0]
        if not fragmentos:
            return {"respuesta": "", "puntos": [], "citas": [],
                    "abstencion": "No encontré documentos vigentes que respondan esa pregunta."}
        ctx = {"pregunta": pregunta, "fragmentos": fragmentos}
        mensajes = [{"role": "system", "content": SISTEMA_PREGUNTA}, {"role": "user", "content": (
            f"Pregunta del docente: {pregunta}\n\nFragmentos:\n"
            + "\n\n".join(f"[{f['id']}] {f['titulo']} (versión {f['version']}, p. {f['pagina']})\n{f['texto']}"
                          for f in fragmentos)
            + '\n\nDevuelve {"contenido": {"respuesta": "...", "puntos": []}, "fuentes": [], '
              '"abstencion": null, "notas": null}.')}]
        try:
            r = tarea.generar(mensajes, SalidaRespuesta, contexto=ctx,
                              fragmentos_validos=[f["id"] for f in fragmentos])
        except ErrorHarness as error:
            return {"respuesta": "", "puntos": [], "citas": [], "abstencion": str(error)}
        por_id = {f["id"]: f for f in fragmentos}
        citas = r.citas_validas or [fragmentos[0]["id"]]
        return {
            "respuesta": r.salida.contenido.respuesta, "puntos": r.salida.contenido.puntos,
            "abstencion": r.salida.abstencion,
            "citas": [{"fragmento_id": i, "documento": por_id[i]["titulo"], "version": por_id[i]["version"],
                       "pagina": por_id[i]["pagina"], "texto": por_id[i]["texto"][:900]}
                      for i in citas if i in por_id],
        }


def _mensajes(evento: dict, fragmentos: list[dict]) -> list[dict[str, str]]:
    datos = {k: v for k, v in evento.items() if k not in ("fragmentos_evento", "consulta", "autor_id")}
    texto = "\n\n".join(
        f"[{f['id']}] {f['titulo']} (versión {f['version']}, p. {f['pagina']})\n{f['texto']}"
        for f in fragmentos
    ) or "(sin fragmentos)"
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": (
        f"Evento:\n{json.dumps(datos, ensure_ascii=False, indent=2, default=str)}\n\n"
        f"Fragmentos (lo nuevo o cambiado y lo relacionado del corpus):\n{texto}\n\n"
        'Devuelve {"contenido": {"titulo": "...", "resumen": "...", "puntos": [], '
        '"secciones_afectadas": []}, "fuentes": [], "abstencion": null, "notas": null}.'
    )}]


def noticia_dict(n: Noticia) -> dict:
    return {"id": n.id, "titulo": n.titulo, "resumen": n.resumen, "puntos": n.puntos or [],
            "categoria": n.categoria, "origen": n.origen, "carrera": n.carrera,
            "importante": n.importante, "documento_id": n.documento_id, "fuente_url": n.fuente_url,
            "citas": n.citas or [], "fecha": n.fecha.isoformat()}
