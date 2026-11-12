"""Operaciones del agente sobre un sílabo: generar, editar, aprobar, verificar y exportar.

Cada sección generada sigue el mismo ciclo (SPEC 7.1): recuperar evidencia -> decidir si es
suficiente (o abstenerse) -> generar con citas -> aplicar los datos bloqueados -> validar ->
guardar la versión. El grafo de LangGraph (`grafo.py`) decide el orden y las pausas; este
módulo hace el trabajo y lo deja registrado en la base relacional.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from syllabusai.agent import herramientas, indicaciones, planificacion
from syllabusai.agent.harness import ErrorHarness, Harness
from syllabusai.config import Config
from syllabusai.db.modelos import (
    Asignatura,
    Cita,
    Documento,
    EstadoDocumento,
    EstadoSeccion,
    EstadoSilabo,
    Hallazgo,
    OrigenVersion,
    Seccion,
    Severidad,
    Silabo,
    Usuario,
    VersionSeccion,
)
from syllabusai.esquemas import FichaCurricular
from syllabusai.formato.definicion import DefinicionSeccion, Formato
from syllabusai.formato.esquemas import ESQUEMAS, contenido_vacio
from syllabusai.ingest.catalogo import ficha_de
from syllabusai.llm.base import ClienteLLM
from syllabusai.llm.prompts import VERSION_PROMPTS, construir_mensajes, esquema_salida
from syllabusai.retrieval.lexico import normalizar
from syllabusai.retrieval.recuperador import FragmentoRecuperado, Recuperador
from syllabusai.telemetry.eventos import distancia_edicion, registrar, texto_plano
from syllabusai.validation import reglas
from syllabusai.validation.reglas import EstadoSeccionValidable


class ErrorServicio(ValueError):
    """Operación no permitida en el estado actual del sílabo."""


class ServicioSilabos:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        recuperador: Recuperador,
        llm: ClienteLLM,
        formato: Formato,
        config: Config,
    ):
        self.fabrica = fabrica
        self.recuperador = recuperador
        self.llm = llm
        self.formato = formato
        self.config = config
        # Quien sigue en vivo la generación de un sílabo (API en streaming, RNF-07).
        self.oyentes: dict[int, Callable[[dict], None]] = {}

    @property
    def harness(self) -> Harness:
        # Se construye sobre el modelo vigente: las pruebas y la API pueden cambiarlo en caliente.
        return Harness(self.llm)

    def _emitir(self, silabo_id: int, tipo: str, **datos) -> None:
        oyente = self.oyentes.get(silabo_id)
        if oyente is not None:
            oyente({"tipo": tipo} | datos)

    # --- creación ------------------------------------------------------------------------

    def crear_silabo(
        self, docente_id: int, asignatura_id: int, periodo: str, datos_generales: dict[str, Any]
    ) -> int:
        with self.fabrica() as sesion:
            asignatura = sesion.get(Asignatura, asignatura_id)
            if asignatura is None:
                raise ErrorServicio(f"No existe la asignatura {asignatura_id}")
            ficha_de(asignatura)  # falla aquí si la ficha curricular está incompleta
            # Las indicaciones generales del docente se interpretan una vez y quedan como
            # preferencias que el agente recuerda en todas las secciones.
            datos = dict(datos_generales)
            inicial = indicaciones.interpretar(datos.get("indicaciones_generales"))
            datos["preferencias"] = indicaciones.fusionar(datos.get("preferencias"), inicial)
            datos |= {k: v for k, v in inicial.datos.items() if not str(datos.get(k) or "").strip()}
            datos["interpretacion_inicial"] = {
                "entendido": inicial.entendido, "rechazado": inicial.rechazado,
                "no_entendido": inicial.no_entendido,
            }
            silabo = Silabo(
                asignatura=asignatura, docente_id=docente_id, periodo=periodo,
                datos_generales=datos,
            )
            for orden, definicion in enumerate(self.formato.secciones, start=1):
                silabo.secciones.append(Seccion(clave=definicion.clave, orden=orden))
            sesion.add(silabo)
            sesion.flush()
            registrar(sesion, "creacion", silabo_id=silabo.id,
                      payload={"asignatura": asignatura.codigo, "formato": self.formato.version})
            sesion.commit()
            return silabo.id

    # --- utilidades internas -------------------------------------------------------------

    def _silabo(self, sesion: Session, silabo_id: int) -> Silabo:
        silabo = sesion.get(Silabo, silabo_id)
        if silabo is None:
            raise ErrorServicio(f"No existe el sílabo {silabo_id}")
        return silabo

    @staticmethod
    def _seccion(silabo: Silabo, clave: str) -> Seccion:
        for seccion in silabo.secciones:
            if seccion.clave == clave:
                return seccion
        raise ErrorServicio(f"El sílabo no tiene la sección «{clave}»")

    @staticmethod
    def ultima_version(seccion: Seccion, origen: OrigenVersion | None = None) -> VersionSeccion | None:
        versiones = [v for v in seccion.versiones if origen is None or v.origen == origen]
        return versiones[-1] if versiones else None

    def _contenido_actual(self, seccion: Seccion) -> dict:
        version = self.ultima_version(seccion)
        return version.contenido if version else contenido_vacio(seccion.clave)

    def _contexto(
        self, silabo: Silabo, definicion: DefinicionSeccion, indicacion: str | None,
        local: dict | None = None,
    ) -> dict[str, Any]:
        asignatura = silabo.asignatura
        ficha = ficha_de(asignatura)
        datos = {k: v for k, v in silabo.datos_generales.items()
                 if k not in ("preferencias", "interpretacion_inicial")}
        preferencias = indicaciones.preferencias_de(silabo.datos_generales)
        pesos, aviso_pesos = indicaciones.pesos_momentos(preferencias.pesos)
        aprobadas = {
            s.clave: self._contenido_actual(s)
            for s in silabo.secciones
            if s.estado == EstadoSeccion.APROBADA and s.clave != definicion.clave
        }
        esqueleto = planificacion.esqueleto_momentos(
            ficha, int(datos.get("semanas_periodo") or 16), pesos
        )
        contexto = {
            "asignatura": {
                "codigo": asignatura.codigo, "nombre": asignatura.nombre,
                "carrera": asignatura.carrera, "nivel": asignatura.nivel,
                "creditos": asignatura.creditos, "horas": asignatura.horas,
                "prerrequisitos": list(asignatura.prerrequisitos),
            },
            "ficha": ficha.model_dump(mode="json"),
            "datos_generales": datos,
            "aprobadas": aprobadas,
            "esqueleto_momentos": esqueleto,
            "momentos_de_ra": planificacion.momentos_de_ra(esqueleto),
            "indicacion": indicacion,
            "preferencias": preferencias.model_dump(mode="json"),
            "local": local or {},
            "aviso_pesos": aviso_pesos,
        }
        planeacion = aprobadas.get("planeacion_momentos")
        if planeacion:
            contexto["esqueleto_evaluacion"] = planificacion.esqueleto_evaluacion(planeacion["momentos"])
        return contexto

    @staticmethod
    def _fragmentos_para_prompt(fragmentos: list[FragmentoRecuperado]) -> list[dict]:
        return [
            {
                "id": r.fragmento.fragmento_id, "titulo": r.fragmento.titulo,
                "tipo": str(r.fragmento.tipo_documento), "version": r.fragmento.version,
                "pagina": r.fragmento.pagina_inicio, "ruta": r.fragmento.ruta_seccion,
                "texto": r.fragmento.texto,
            }
            for r in fragmentos
        ]

    def _registro_busqueda(self, sesion: Session, silabo_id: int, clave: str):
        def registro(consulta, filtros, resultados, latencia_ms):
            registrar(
                sesion, "busqueda", silabo_id=silabo_id, paso=clave, latencia_ms=latencia_ms,
                payload={"consulta": consulta, "filtros": filtros, "resultados": [
                    {"fragmento_id": r.fragmento.fragmento_id, "puntaje": r.puntaje,
                     "puntaje_lexico": r.puntaje_lexico} for r in resultados
                ]},
            )
        return registro

    # --- generación ----------------------------------------------------------------------

    def generar_seccion(self, silabo_id: int, clave: str, indicacion: str | None = None) -> dict:
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            seccion = self._seccion(silabo, clave)
            if seccion.estado == EstadoSeccion.APROBADA:
                raise ErrorServicio(f"La sección «{clave}» ya está aprobada; reábrala para regenerarla")
            definicion = self.formato.seccion(clave)
            inicio = time.perf_counter()
            # Lo que el docente pide se interpreta primero: las preferencias se recuerdan para
            # el resto del sílabo; el énfasis, la extensión y los criterios son de esta sección.
            interpretacion = indicaciones.interpretar(indicacion)
            avisos = self._recordar(silabo, interpretacion) if interpretacion.campos else []
            if definicion.tipo == "importada":
                resultado = self._generar_importada(silabo, clave)
            else:
                resultado = self._generar_con_modelo(
                    sesion, silabo, definicion, indicacion, interpretacion.local()
                )
            contenido, fuentes, abstencion, extra, metricas = resultado

            nota = self._nota(silabo, clave, interpretacion, abstencion, metricas, avisos)
            version = self._guardar_version(seccion, OrigenVersion.AGENTE, contenido, fuentes,
                                            indicacion=indicacion, nota=nota)
            seccion.estado = EstadoSeccion.ABSTENIDA if abstencion else EstadoSeccion.PROPUESTA
            if silabo.estado == EstadoSilabo.BORRADOR:
                silabo.estado = EstadoSilabo.EN_REVISION
            hallazgos = extra
            if abstencion:
                hallazgos = [reglas.Hallazgo("RF-14", Severidad.BLOQUEANTE,
                                             f"Abstención: {abstencion}", clave)] + extra
            else:
                hallazgos += self._validar_version(silabo, seccion, version)
            self._reemplazar_hallazgos(sesion, silabo, hallazgos, seccion)
            registrar(
                sesion, "generacion", silabo_id=silabo.id, paso=clave,
                latencia_ms=metricas.get("latencia_ms", (time.perf_counter() - inicio) * 1000),
                ttft_ms=metricas.get("ttft_ms"), tokens_in=metricas.get("tokens_in"),
                tokens_out=metricas.get("tokens_out"),
                payload={
                    "version": version.n, "abstencion": abstencion, "indicacion": indicacion,
                    "entendido": interpretacion.entendido,
                    "no_entendido": interpretacion.no_entendido,
                    "rechazado": interpretacion.rechazado,
                    "fuentes": [f.fragmento.fragmento_id for f in fuentes],
                    "fragmentos_recuperados": metricas.get("fragmentos", 0),
                    "modelo": metricas.get("modelo"), "prompts": VERSION_PROMPTS,
                    "latencia_total_ms": (time.perf_counter() - inicio) * 1000,
                },
            )
            sesion.commit()
            self._emitir(silabo_id, "listo", clave=clave, estado=str(seccion.estado))
            return self._resumen_seccion(seccion)

    def actualizar_preferencias(self, silabo_id: int, preferencias: dict) -> dict:
        """El docente corrige a mano lo que el agente recuerda; rige desde la próxima sección."""
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            nuevas = indicaciones.Preferencias.model_validate(preferencias).model_dump(mode="json")
            _, aviso = indicaciones.pesos_momentos(nuevas["pesos"])
            if aviso:
                raise ErrorServicio(aviso)
            silabo.datos_generales = dict(silabo.datos_generales) | {"preferencias": nuevas}
            registrar(sesion, "preferencias", silabo_id=silabo.id, payload=nuevas)
            sesion.commit()
            return nuevas

    def _recordar(self, silabo: Silabo, interpretacion: indicaciones.Interpretacion) -> list[str]:
        """Guarda lo pedido en las preferencias del sílabo. Lo imposible no se guarda: se avisa."""
        datos = dict(silabo.datos_generales)
        anteriores = indicaciones.preferencias_de(datos)
        nuevas = indicaciones.fusionar(datos.get("preferencias"), interpretacion)
        avisos = []
        _, aviso = indicaciones.pesos_momentos(nuevas["pesos"])
        if aviso:
            nuevas["pesos"] = anteriores.pesos
            interpretacion.cambios.pop("pesos", None)
            avisos.append(aviso + " No los guardé.")
        datos["preferencias"] = nuevas
        datos |= interpretacion.datos
        silabo.datos_generales = datos  # objeto nuevo: SQLAlchemy detecta el cambio del JSON
        return avisos

    def _nota(
        self, silabo: Silabo, clave: str, interpretacion: indicaciones.Interpretacion,
        abstencion: str | None, metricas: dict, avisos: list[str] | None = None,
    ) -> str | None:
        """Respuesta del agente al docente: qué entendió, qué aplicó y qué deja para después."""
        partes = []
        if interpretacion.entendido:
            partes.append("Entendí: " + "; ".join(interpretacion.entendido) + ".")
        partes += avisos or []
        titulos = {d.clave: f"{d.numero} {d.titulo}" for d in self.formato.secciones}
        estados = {s.clave: s.estado for s in silabo.secciones}
        afectadas = {c for campo in interpretacion.campos
                     for c in indicaciones.SECCIONES_DE.get(campo, [])}
        despues = [titulos[c] for c in self.formato.claves
                   if c in afectadas and c != clave and estados.get(c) != EstadoSeccion.APROBADA]
        aprobadas = [titulos[c] for c in self.formato.claves
                     if c in afectadas and c != clave and estados.get(c) == EstadoSeccion.APROBADA]
        local = interpretacion.local()
        if not abstencion and (clave in afectadas or any(local.values())):
            partes.append("Ya lo apliqué en esta propuesta.")
        elif interpretacion.campos and clave not in afectadas:
            partes.append("Esta sección no cambia con eso, pero lo guardé en sus preferencias.")
        if despues:
            partes.append("Lo tendré en cuenta en: " + "; ".join(despues) + ".")
        if aprobadas:
            partes.append("También afecta a secciones ya aprobadas (" + "; ".join(aprobadas)
                          + "): reábralas al final si quiere aplicarlo allí.")
        partes += interpretacion.rechazado
        if interpretacion.no_entendido:
            textos = "; ".join(f"«{x}»" for x in interpretacion.no_entendido)
            if self.llm.nombre == "simulado":
                partes.append(f"No supe interpretar {textos}. En modo simulado entiendo pedidos como: "
                              "«en equipos de 3», «sin IA», «usa Python», «agrega coevaluación», «el "
                              "producto será…», «el reto sobre…», «momento 3 con 30 %», «agrega la "
                              "referencia: …», «agrega el criterio: …», «más breve», «énfasis en…». "
                              "El modelo real interpreta texto libre.")
            else:
                partes.append(f"Pasé al modelo, tal cual, {textos}.")
        if metricas.get("aviso_pesos"):
            partes.append(metricas["aviso_pesos"])
        if metricas.get("notas_modelo"):
            partes.append(metricas["notas_modelo"])
        if abstencion:
            if clave == "problema_reto":
                salida = ("Puede darme lo que falta aquí mismo, por ejemplo: «El problema es que … "
                          "(fuente: …)», o completar la sección usted.")
            else:
                salida = ("Puede completar la sección usted o pedir al administrador del corpus que "
                          "cargue el documento que falta y luego regenerarla.")
            partes.append(f"No redacté la sección: {abstencion} {salida}")
        return " ".join(partes) or None

    def _generar_importada(self, silabo: Silabo, clave: str):
        if clave != "identificacion":
            raise ErrorServicio(f"No hay importación definida para «{clave}»")
        a, ficha, datos = silabo.asignatura, ficha_de(silabo.asignatura), silabo.datos_generales
        docente: Usuario = silabo.docente
        contenido = {
            "nombre_pf": a.nombre, "codigo": a.codigo, "version": str(datos.get("version") or "1"),
            "facultad": ficha.facultad or self.formato.facultad, "carrera": a.carrera,
            "nivel": str(a.nivel), "modalidad": ficha.modalidad,
            "unidad_organizacion": ficha.unidad_organizacion, "periodo_academico": silabo.periodo,
            "creditos": a.creditos, "horas_contacto": ficha.horas_contacto,
            "horas_practicas": ficha.horas_practicas, "horas_autonomas": ficha.horas_autonomas,
            "total_horas": ficha.total_horas, "prerrequisitos": list(a.prerrequisitos),
            "correquisitos": list(ficha.correquisitos),
            "docente": datos.get("docente") or docente.nombre,
            "correo_docente": datos.get("correo_docente") or docente.correo,
        }
        return contenido, [], None, [], {"modelo": "importacion"}

    def _generar_con_modelo(
        self, sesion, silabo: Silabo, definicion: DefinicionSeccion, indicacion, local: dict
    ):
        contexto = self._contexto(silabo, definicion, indicacion, local)
        clave = definicion.clave
        faltan = [d for d in definicion.requiere_datos if not str(contexto["datos_generales"].get(d) or "").strip()]
        faltan += [d for d in definicion.requiere_ficha if not contexto["ficha"].get(d)]
        if faltan:
            return contenido_vacio(clave), [], f"faltan datos requeridos: {', '.join(faltan)}.", [], {}

        variables = {"carrera": silabo.asignatura.carrera, "asignatura": silabo.asignatura.nombre}
        self._emitir(silabo.id, "paso", clave=clave, texto="Buscando evidencia en el corpus vigente…")
        fragmentos = herramientas.recuperar_evidencia(
            self.recuperador, definicion, variables,
            registro=self._registro_busqueda(sesion, silabo.id, clave),
        )
        tipos_faltantes = herramientas.evidencia_suficiente(
            fragmentos, definicion.tipos_requeridos, self.config.recuperacion.min_fragmentos
        )
        if tipos_faltantes:
            nombres = ", ".join(str(t) for t in tipos_faltantes)
            motivo = (f"no hay evidencia suficiente en documentos vigentes de tipo: {nombres}. "
                      "Cargue o marque como vigentes esos documentos.")
            return contenido_vacio(clave), [], motivo, [], {"fragmentos": len(fragmentos)}

        if clave == "recursos":
            # La bibliografía que aporta el docente también es una fuente válida.
            contexto["candidatos_bibliografia"] = herramientas.candidatos_bibliografia(
                contexto["preferencias"]["bibliografia"] + contexto["ficha"].get("bibliografia", []),
                fragmentos, silabo.asignatura.nombre,
            )
        contexto["fragmentos"] = self._fragmentos_para_prompt(fragmentos)
        self._emitir(silabo.id, "paso", clave=clave, texto=(
            f"Redactando con el modelo «{self.llm.nombre}» a partir de {len(fragmentos)} fragmentos…"))
        salida, respuesta = self._llamar_modelo(
            definicion, contexto, lambda trozo: self._emitir(silabo.id, "token", texto=trozo)
        )
        self._emitir(silabo.id, "paso", clave=clave, texto="Validando la propuesta…")
        metricas = {
            "latencia_ms": respuesta.latencia_ms, "ttft_ms": respuesta.ttft_ms,
            "tokens_in": respuesta.tokens_in, "tokens_out": respuesta.tokens_out,
            "modelo": respuesta.modelo, "fragmentos": len(fragmentos),
            "aviso_pesos": contexto["aviso_pesos"] if clave == "planeacion_momentos" else None,
            "notas_modelo": salida.notas,
        }
        if salida.abstencion:
            return contenido_vacio(clave), [], salida.abstencion, [], metricas

        contenido, extra = aplicar_bloqueos(clave, salida.contenido.model_dump(mode="json"), contexto)
        por_id = {f.fragmento.fragmento_id: f for f in fragmentos}
        fuentes, invalidas = [], []
        for fid in dict.fromkeys(salida.fuentes):
            if fid in por_id:
                fuentes.append(por_id[fid])
            else:
                invalidas.append(fid)
        if invalidas:
            extra.append(reglas.Hallazgo(
                "RF-13", Severidad.ADVERTENCIA, "El modelo citó fragmentos que no se le entregaron; "
                f"se descartaron: {', '.join(invalidas)}.", clave,
            ))
        return contenido, fuentes, None, extra, metricas

    def _llamar_modelo(
        self, definicion: DefinicionSeccion, contexto: dict,
        al_token: Callable[[str], None] | None = None,
    ):
        """La sección se genera dentro del harness: salida validada contra el esquema de la
        sección, con un reintento que le devuelve al modelo el error de validación."""
        try:
            resultado = self.harness.generar(
                definicion.clave, construir_mensajes(definicion, contexto),
                esquema_salida(definicion.clave), contexto=contexto, al_token=al_token,
            )
        except ErrorHarness as error:
            raise ErrorServicio(str(error)) from error
        return resultado.salida, resultado.respuesta

    def _guardar_version(
        self, seccion: Seccion, origen: OrigenVersion, contenido: dict,
        fuentes: list[FragmentoRecuperado], indicacion: str | None = None, nota: str | None = None,
    ) -> VersionSeccion:
        n = (seccion.versiones[-1].n if seccion.versiones else 0) + 1
        version = VersionSeccion(n=n, origen=origen, contenido=contenido, indicacion=indicacion,
                                 nota=nota)
        for r in fuentes:
            f = r.fragmento
            version.citas.append(Cita(
                fragmento_id=f.fragmento_id, documento_id=f.documento_id,
                pagina=f.pagina_inicio, texto_citado=f.texto[:1500],
            ))
        seccion.versiones.append(version)
        return version

    def _validar_version(self, silabo: Silabo, seccion: Seccion, version: VersionSeccion):
        ficha = ficha_de(silabo.asignatura)
        hallazgos = reglas.validar_seccion(seccion.clave, version.contenido, ficha, silabo.datos_generales)
        if seccion.clave in reglas.CON_EVIDENCIA and not version.citas:
            hallazgos.append(reglas.sin_fuentes(seccion.clave, version.origen == OrigenVersion.DOCENTE))
        return hallazgos

    def _reemplazar_hallazgos(
        self, sesion: Session, silabo: Silabo, hallazgos: list[reglas.Hallazgo],
        seccion: Seccion | None = None,
    ) -> None:
        """Sustituye los hallazgos abiertos; respeta las advertencias ya descartadas (RF-36)."""
        consulta = delete(Hallazgo).where(Hallazgo.silabo_id == silabo.id, Hallazgo.resuelto.is_(False))
        if seccion is not None:
            consulta = consulta.where(Hallazgo.seccion_id == seccion.id)
        sesion.execute(consulta)
        sesion.expire(silabo, ["hallazgos"])
        descartados = {(h.regla, h.seccion_id, h.mensaje) for h in silabo.hallazgos if h.resuelto}
        ids = {s.clave: s.id for s in silabo.secciones}
        for h in hallazgos:
            seccion_id = ids.get(h.clave) if h.clave else None
            if (h.regla, seccion_id, h.mensaje) in descartados:
                continue
            sesion.add(Hallazgo(silabo_id=silabo.id, seccion_id=seccion_id, regla=h.regla,
                                severidad=h.severidad, mensaje=h.mensaje))
        sesion.flush()
        # Los hallazgos se crearon por clave foránea: la colección cargada ya no es válida.
        sesion.expire(silabo, ["hallazgos"])

    # --- revisión docente ----------------------------------------------------------------

    def editar_seccion(self, silabo_id: int, clave: str, contenido: dict) -> dict:
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            seccion = self._seccion(silabo, clave)
            if seccion.estado == EstadoSeccion.APROBADA:
                raise ErrorServicio(f"La sección «{clave}» ya está aprobada; reábrala para editarla")
            try:
                contenido = ESQUEMAS[clave].model_validate(contenido).model_dump(mode="json")
            except ValidationError as error:
                raise ErrorServicio(f"El contenido no cumple el esquema de «{clave}»: {error}") from error
            anterior = self.ultima_version(seccion)
            # La edición conserva las citas de la propuesta en la que se basa.
            fuentes = []
            if anterior is not None:
                fuentes = self._fragmentos_citados(anterior)
            version = self._guardar_version(seccion, OrigenVersion.DOCENTE, contenido, fuentes)
            seccion.estado = EstadoSeccion.PROPUESTA
            self._reemplazar_hallazgos(sesion, silabo, self._validar_version(silabo, seccion, version), seccion)
            propuesta = self.ultima_version(seccion, OrigenVersion.AGENTE)
            registrar(sesion, "correccion", silabo_id=silabo.id, paso=clave, payload={
                "version": version.n,
                "distancia_edicion": distancia_edicion(
                    texto_plano(propuesta.contenido if propuesta else {}), texto_plano(contenido)
                ),
                "palabras_propuestas": len(texto_plano(propuesta.contenido if propuesta else {}).split()),
            })
            sesion.commit()
            return self._resumen_seccion(seccion)

    def _fragmentos_citados(self, version: VersionSeccion) -> list[FragmentoRecuperado]:
        payloads = self.recuperador.almacen.obtener([c.fragmento_id for c in version.citas])
        return [FragmentoRecuperado(p, 0.0, 0.0) for p in payloads.values()]

    def aprobar_seccion(self, silabo_id: int, clave: str) -> dict:
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            seccion = self._seccion(silabo, clave)
            if not seccion.versiones:
                raise ErrorServicio(f"La sección «{clave}» todavía no tiene contenido")
            if seccion.estado == EstadoSeccion.ABSTENIDA:
                raise ErrorServicio("La sección está en abstención: complétela editándola o "
                                    "regenérela tras cargar la evidencia faltante")
            seccion.estado = EstadoSeccion.APROBADA
            registrar(sesion, "aprobacion", silabo_id=silabo.id, paso=clave,
                      payload={"version": seccion.versiones[-1].n,
                               "origen": str(seccion.versiones[-1].origen)})
            sesion.commit()
            return self._resumen_seccion(seccion)

    def reabrir_seccion(self, silabo_id: int, clave: str) -> dict:
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            seccion = self._seccion(silabo, clave)
            seccion.estado = EstadoSeccion.PROPUESTA if seccion.versiones else EstadoSeccion.PENDIENTE
            if silabo.estado in (EstadoSilabo.APROBADO, EstadoSilabo.EXPORTADO):
                silabo.estado = EstadoSilabo.EN_REVISION
            registrar(sesion, "reapertura", silabo_id=silabo.id, paso=clave)
            sesion.commit()
            return self._resumen_seccion(seccion)

    def descartar_advertencia(self, silabo_id: int, hallazgo_id: int, justificacion: str) -> None:
        with self.fabrica() as sesion:
            hallazgo = sesion.get(Hallazgo, hallazgo_id)
            if hallazgo is None or hallazgo.silabo_id != silabo_id:
                raise ErrorServicio(f"No existe el hallazgo {hallazgo_id} en el sílabo")
            if hallazgo.severidad == Severidad.BLOQUEANTE:
                raise ErrorServicio("Un hallazgo bloqueante no se descarta: debe corregirse")
            if not justificacion.strip():
                raise ErrorServicio("Descartar una advertencia exige una justificación")
            hallazgo.resuelto = True
            registrar(sesion, "descarte", silabo_id=silabo_id, payload={
                "hallazgo_id": hallazgo_id, "regla": hallazgo.regla, "justificacion": justificacion,
            })
            sesion.commit()

    # --- verificación y exportación ------------------------------------------------------

    def verificar(self, silabo_id: int) -> list[dict]:
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            vigentes = {d.id for d in sesion.scalars(
                select(Documento).where(Documento.estado == EstadoDocumento.VIGENTE)
            )}
            estados = {}
            for s in silabo.secciones:
                version = self.ultima_version(s)
                citas = version.citas if version else []
                estados[s.clave] = EstadoSeccionValidable(
                    clave=s.clave, estado=s.estado, contenido=self._contenido_actual(s),
                    citas_validas=sum(1 for c in citas if c.documento_id in vigentes),
                    citas_obsoletas=sum(1 for c in citas if c.documento_id not in vigentes),
                    redactada_por_docente=version is not None and version.origen == OrigenVersion.DOCENTE,
                )
            hallazgos = reglas.validar_silabo(
                self.formato.claves, estados, ficha_de(silabo.asignatura), silabo.datos_generales
            )
            self._reemplazar_hallazgos(sesion, silabo, hallazgos)
            bloqueantes = sum(1 for h in hallazgos if h.severidad == Severidad.BLOQUEANTE)
            todas = all(s.estado == EstadoSeccion.APROBADA for s in silabo.secciones)
            if todas and not bloqueantes and silabo.estado != EstadoSilabo.EXPORTADO:
                silabo.estado = EstadoSilabo.APROBADO
            registrar(sesion, "verificacion", silabo_id=silabo.id, payload={
                "bloqueantes": bloqueantes, "advertencias": len(hallazgos) - bloqueantes,
            })
            sesion.commit()
            return self._hallazgos(silabo)

    def guardar_documento(self, silabo_id: int, secciones: dict[str, dict]) -> dict:
        """Correcciones del docente sobre el documento completo, después de aprobar el flujo.

        Cada sección que cambió queda como una versión nueva de origen docente (con las citas de
        la versión en que se basa) y sigue aprobada; luego se verifica el sílabo entero. Los
        cambios a datos oficiales no se impiden: la verificación los señala.
        """
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            cambiadas = []
            for clave, contenido in secciones.items():
                seccion = self._seccion(silabo, clave)
                try:
                    limpio = ESQUEMAS[clave].model_validate(contenido).model_dump(mode="json")
                except ValidationError as error:
                    raise ErrorServicio(f"El contenido no cumple el esquema de «{clave}»: {error}") from error
                anterior = self.ultima_version(seccion)
                if anterior is not None and anterior.contenido == limpio:
                    continue
                fuentes = self._fragmentos_citados(anterior) if anterior is not None else []
                version = self._guardar_version(seccion, OrigenVersion.DOCENTE, limpio, fuentes,
                                                nota="Corrección en el documento final")
                if seccion.estado != EstadoSeccion.APROBADA:
                    seccion.estado = EstadoSeccion.PROPUESTA
                propuesta = self.ultima_version(seccion, OrigenVersion.AGENTE)
                registrar(sesion, "correccion", silabo_id=silabo.id, paso=clave, payload={
                    "version": version.n, "documento_final": True,
                    "distancia_edicion": distancia_edicion(
                        texto_plano(propuesta.contenido if propuesta else {}), texto_plano(limpio)),
                })
                cambiadas.append(clave)
            if cambiadas and silabo.estado == EstadoSilabo.EXPORTADO:
                silabo.estado = EstadoSilabo.APROBADO
            sesion.commit()
        self.verificar(silabo_id)
        return {"cambiadas": cambiadas}

    def exportar(self, silabo_id: int, formato: str = "docx", borrador: bool = False) -> Path:
        """Exporta el sílabo. La versión final exige todas las secciones aprobadas y ningún
        hallazgo bloqueante (RF-42, RF-36); el borrador se exporta siempre, marcado como tal y
        con las observaciones pendientes al final."""
        from syllabusai.export import exportar_silabo

        self.verificar(silabo_id)
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            pendientes = [s.clave for s in silabo.secciones if s.estado != EstadoSeccion.APROBADA]
            abiertos = [h for h in silabo.hallazgos
                        if not h.resuelto and h.severidad == Severidad.BLOQUEANTE]
            if not borrador:
                if pendientes:
                    raise ErrorServicio(f"Hay secciones sin aprobar: {', '.join(pendientes)} (RF-42)")
                if abiertos:
                    raise ErrorServicio(f"Hay {len(abiertos)} hallazgo(s) bloqueante(s) sin resolver (RF-36)")
            inicio = time.perf_counter()
            datos = self.datos_exportacion(silabo)
            if borrador:
                datos["borrador"] = True
                datos["observaciones"] = [
                    f"[{h.severidad}] {h.regla}: {h.mensaje}" for h in silabo.hallazgos if not h.resuelto
                ] + [f"Sección sin aprobar: {c}" for c in pendientes]
            ruta = exportar_silabo(datos, formato, self.config.exportacion)
            if not borrador:
                silabo.estado = EstadoSilabo.EXPORTADO
            creado = silabo.creado if silabo.creado.tzinfo else silabo.creado.replace(tzinfo=UTC)
            registrar(sesion, "exportacion", silabo_id=silabo.id, paso=formato,
                      latencia_ms=(time.perf_counter() - inicio) * 1000,
                      payload={"archivo": str(ruta), "borrador": borrador,
                               "duracion_sesion_min": (datetime.now(UTC) - creado).total_seconds() / 60})
            sesion.commit()
            return ruta

    def datos_exportacion(self, silabo: Silabo) -> dict:
        from syllabusai.db.modelos import ProyectoIntegrador

        pis = Session.object_session(silabo).scalar(
            select(ProyectoIntegrador).where(ProyectoIntegrador.silabo_id == silabo.id))
        return {
            "pis": pis.contenido if pis is not None and pis.estado != "vacio" else None,
            "formato": {"nombre": self.formato.nombre, "version": self.formato.version},
            "silabo": {"id": silabo.id, "periodo": silabo.periodo,
                       "datos_generales": silabo.datos_generales},
            "secciones": {s.clave: self._contenido_actual(s) for s in silabo.secciones},
            "titulos": {d.clave: f"{d.numero}. {d.titulo}" for d in self.formato.secciones},
            "fuentes": {
                s.clave: [
                    {"documento": c.documento.titulo, "version": c.documento.version,
                     "pagina": c.pagina, "fragmento_id": c.fragmento_id}
                    for c in (self.ultima_version(s).citas if self.ultima_version(s) else [])
                ]
                for s in silabo.secciones
            },
        }

    # --- consultas -----------------------------------------------------------------------

    def _resumen_seccion(self, seccion: Seccion) -> dict:
        version = self.ultima_version(seccion)
        return {
            "clave": seccion.clave, "orden": seccion.orden, "estado": str(seccion.estado),
            "version": version.n if version else 0,
            "origen": str(version.origen) if version else None,
            "contenido": version.contenido if version else None,
            "nota": version.nota if version else None,
        }

    @staticmethod
    def _hallazgos(silabo: Silabo) -> list[dict]:
        claves = {s.id: s.clave for s in silabo.secciones}
        return [
            {"id": h.id, "regla": h.regla, "severidad": str(h.severidad), "mensaje": h.mensaje,
             "seccion": claves.get(h.seccion_id), "resuelto": h.resuelto}
            for h in silabo.hallazgos
        ]

    def estado(self, silabo_id: int) -> dict:
        with self.fabrica() as sesion:
            silabo = self._silabo(sesion, silabo_id)
            secciones = []
            for s in silabo.secciones:
                resumen = self._resumen_seccion(s)
                definicion = self.formato.seccion(s.clave)
                version = self.ultima_version(s)
                resumen |= {
                    "titulo": f"{definicion.numero}. {definicion.titulo}",
                    "tipo": definicion.tipo,
                    "citas": [
                        {"fragmento_id": c.fragmento_id, "documento": c.documento.titulo,
                         "version": c.documento.version, "pagina": c.pagina,
                         "vigente": c.documento.estado == EstadoDocumento.VIGENTE,
                         "texto": c.texto_citado}
                        for c in (version.citas if version else [])
                    ],
                    "historial": [{"n": v.n, "origen": str(v.origen), "creado": v.creado.isoformat(),
                                   "indicacion": v.indicacion, "nota": v.nota}
                                  for v in s.versiones],
                }
                secciones.append(resumen)
            return {
                "id": silabo.id, "estado": str(silabo.estado), "periodo": silabo.periodo,
                "asignatura": {"id": silabo.asignatura.id, "codigo": silabo.asignatura.codigo,
                               "nombre": silabo.asignatura.nombre},
                "docente_id": silabo.docente_id,
                "datos_generales": silabo.datos_generales,
                "preferencias": indicaciones.resumen(
                    indicaciones.preferencias_de(silabo.datos_generales)
                ),
                "secciones": secciones,
                "hallazgos": self._hallazgos(silabo),
            }


# --- datos bloqueados ---------------------------------------------------------------------

def _mismo_texto(a: str, b: str) -> bool:
    return " ".join(normalizar(a).split()) == " ".join(normalizar(b).split())


def aplicar_bloqueos(clave: str, contenido: dict, contexto: dict) -> tuple[dict, list[reglas.Hallazgo]]:
    """Impone sobre la propuesta del modelo los datos que no decide el modelo.

    RA, contenidos mínimos y competencia se copian de la ficha; horas, semanas, RA por momento y
    pesos se copian de las herramientas de planificación. Si el modelo los había alterado, queda
    constancia como advertencia.
    """
    ficha = FichaCurricular.model_validate(contexto["ficha"])
    avisos: list[reglas.Hallazgo] = []

    def aviso(mensaje: str) -> None:
        avisos.append(reglas.Hallazgo("CUR-01", Severidad.ADVERTENCIA, mensaje, clave))

    if clave == "anclaje_curricular":
        if ficha.competencia_especifica:
            if not _mismo_texto(contenido.get("competencia_especifica", ""), ficha.competencia_especifica):
                aviso("El modelo alteró la competencia específica; se restituyó la aprobada.")
            contenido["competencia_especifica"] = ficha.competencia_especifica
        for campo in ("pis_periodo", "microcredencial"):
            if getattr(ficha, campo):
                contenido[campo] = getattr(ficha, campo)

    elif clave == "resultados_aprendizaje":
        propuestos = {r.get("codigo"): r for r in contenido.get("resultados", [])}
        momentos = contexto.get("momentos_de_ra", {})
        resultados = []
        for oficial in ficha.resultados_aprendizaje:
            propio = propuestos.get(oficial.codigo, {})
            if propio and not _mismo_texto(propio.get("enunciado", ""), oficial.enunciado):
                aviso(f"El modelo reescribió el {oficial.codigo}; se restituyó el enunciado oficial.")
            resultados.append({
                "codigo": oficial.codigo, "enunciado": oficial.enunciado,
                "evidencia": propio.get("evidencia", ""),
                "momentos": propio.get("momentos") or momentos.get(oficial.codigo, []),
            })
        contenido["resultados"] = resultados

    elif clave == "contenidos":
        presentes = contenido.get("contenidos_minimos", [])
        if len(presentes) != len(ficha.contenidos_minimos) or not all(
            _mismo_texto(a, b) for a, b in zip(presentes, ficha.contenidos_minimos, strict=False)
        ):
            aviso("El modelo alteró los contenidos mínimos; se restituyeron los oficiales.")
        contenido["contenidos_minimos"] = list(ficha.contenidos_minimos)

    elif clave == "planeacion_momentos":
        propuestos = {m.get("numero"): m for m in contenido.get("momentos", [])}
        momentos = []
        for base in contexto["esqueleto_momentos"]:
            propio = dict(propuestos.get(base["numero"], {"numero": base["numero"]}))
            evaluacion = dict(propio.get("evaluacion") or {})
            evaluacion["peso"] = base["peso"]
            evaluacion.setdefault("evidencia", propio.get("evidencia_parcial", ""))
            propio |= {k: base[k] for k in ("numero", "semanas", "ra", "horas_contacto",
                                            "horas_practicas", "horas_autonomas")}
            propio["nombre"] = propio.get("nombre") or base["nombre"]
            propio["evaluacion"] = evaluacion
            momentos.append(propio)
        contenido["momentos"] = momentos

    elif clave == "evaluacion":
        propuestas = {e.get("momento"): e for e in contenido.get("evidencias", [])}
        evidencias = []
        for base in contexto.get("esqueleto_evaluacion", []):
            propia = dict(propuestas.get(base["momento"], {}))
            propia |= {"momento": base["momento"], "ra": base["ra"], "peso": base["peso"]}
            propia["evidencia"] = propia.get("evidencia") or base["evidencia"]
            evidencias.append(propia)
        contenido["evidencias"] = evidencias

    elif clave == "recursos":
        candidatos = [" ".join(normalizar(c).split()) for c in contexto.get("candidatos_bibliografia", [])]
        for campo in ("bibliografia_basica", "bibliografia_complementaria"):
            conservadas = []
            for referencia in contenido.get(campo, []):
                clave_ref = " ".join(normalizar(referencia).split())
                if any(clave_ref[:60] in c or c[:60] in clave_ref for c in candidatos):
                    conservadas.append(referencia)
                else:
                    avisos.append(reglas.Hallazgo(
                        "RF-13", Severidad.ADVERTENCIA, f"Se retiró una referencia que no aparece "
                        f"en las fuentes: «{referencia[:120]}».", clave,
                    ))
            contenido[campo] = conservadas
    return contenido, avisos
