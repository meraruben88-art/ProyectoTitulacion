"""API del prototipo (SPEC, sección 9). Autenticación básica HTTP (RNF-08).

Las acciones de revisión (generar, editar, aprobar) reanudan el grafo del agente en la pausa
pendiente; por eso solo se aceptan sobre la sección que el flujo está esperando. La variante
`/stream` transmite el progreso y el texto del modelo a medida que se generan (RNF-07).
"""

import json
import queue
import shutil
import tempfile
import threading
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import select

from syllabusai.agent import indicaciones
from syllabusai.agent.servicio import ErrorServicio
from syllabusai.contenedor import Contenedor, crear_contenedor
from syllabusai.db.modelos import Asignatura, Documento, EstadoDocumento, Rol, Silabo, TipoDocumento
from syllabusai.esquemas import MetadatosDocumento
from syllabusai.formato.catalogos import (
    EJES,
    HABILIDADES_BLANDAS,
    METACOMPETENCIAS,
    NIVELES_RUBRICA,
)
from syllabusai.ingest.catalogo import ficha_de
from syllabusai.ingest.extraccion import ErrorExtraccion
from syllabusai.ingest.pipeline import procesar_documento, sincronizar_vigencia
from syllabusai.ingest.registro import ErrorRegistro, cambiar_estado, registrar_documento
from syllabusai.llm.base import ErrorLLM
from syllabusai.seguridad import autenticar, usuario_de_token
from syllabusai.telemetry.eventos import exportar as exportar_eventos


@cache
def contenedor_por_defecto() -> Contenedor:
    return crear_contenedor()


def crear_app(obtener_contenedor=contenedor_por_defecto) -> FastAPI:
    app = FastAPI(title="SyllabusAI", version="0.2.0",
                  description="Agente RAG para la creación asistida de sílabos (formato UTI 2026)")
    basica = HTTPBasic(auto_error=False)

    def contenedor() -> Contenedor:
        return obtener_contenedor()

    Cont = Annotated[Contenedor, Depends(contenedor)]

    def usuario_actual(
        c: Cont, request: Request, cred: Annotated[HTTPBasicCredentials | None, Depends(basica)],
    ) -> dict:
        """Usuario de la cookie de sesión (web) o de la autenticación básica (API)."""
        with c.fabrica() as sesion:
            usuario = None
            token = request.cookies.get(c.config.web.cookie)
            if cred is not None:
                usuario = autenticar(sesion, cred.username, cred.password)
            elif token:
                usuario = usuario_de_token(sesion, token)
            if usuario is None:
                # La web no debe abrir el diálogo de autenticación básica del navegador.
                web = request.headers.get("x-syllabusai-web") == "1"
                cabeceras = {} if web else {"WWW-Authenticate": "Basic"}
                raise HTTPException(401, "Credenciales inválidas o sesión vencida", headers=cabeceras)
            return {"id": usuario.id, "nombre": usuario.nombre, "correo": usuario.correo,
                    "rol": str(usuario.rol), "carrera": usuario.carrera}

    Usuario = Annotated[dict, Depends(usuario_actual)]

    def solo_admin(u: Usuario) -> dict:
        if u["rol"] != Rol.ADMIN_CORPUS:
            raise HTTPException(403, "Solo el administrador del corpus puede hacer esto")
        return u

    Admin = Annotated[dict, Depends(solo_admin)]

    def comprobar_silabo(c: Contenedor, u: dict, silabo_id: int, escribir: bool = True) -> None:
        with c.fabrica() as sesion:
            silabo = sesion.get(Silabo, silabo_id)
            if silabo is None:
                raise HTTPException(404, f"No existe el sílabo {silabo_id}")
            if u["rol"] == Rol.DOCENTE and silabo.docente_id != u["id"]:
                raise HTTPException(403, "El sílabo pertenece a otro docente")
            if escribir and u["rol"] == Rol.EVALUADOR:
                raise HTTPException(403, "El evaluador solo puede consultar")

    def con_errores(funcion, *args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except ErrorServicio as error:
            raise HTTPException(409, str(error)) from error
        except (ErrorRegistro, ErrorExtraccion, ValueError) as error:
            raise HTTPException(400, str(error)) from error
        except ErrorLLM as error:
            raise HTTPException(502, str(error)) from error

    def respuesta_silabo(c: Contenedor, silabo_id: int) -> dict:
        return c.servicio.estado(silabo_id) | {"pausa": c.orquestador.pendiente(silabo_id)}

    def exigir_pausa_en(c: Contenedor, silabo_id: int, clave: str) -> None:
        pausa = c.orquestador.pendiente(silabo_id)
        if pausa.get("tipo") != "revision_seccion" or pausa.get("clave") != clave:
            actual = pausa.get("clave") or pausa.get("tipo")
            raise HTTPException(409, f"El flujo no está revisando «{clave}» (pausa actual: {actual})")

    # --- sesión y catálogos ------------------------------------------------------------

    @app.post("/auth/login")
    def login(u: Usuario) -> dict:
        return u

    @app.get("/formato")
    def formato(c: Cont, _: Usuario) -> dict:
        return {
            "nombre": c.formato.nombre, "version": c.formato.version,
            "secciones": [s.model_dump(mode="json", include={"clave", "numero", "titulo", "tipo"})
                          for s in c.formato.secciones],
            "metacompetencias": METACOMPETENCIAS, "ejes": EJES,
            "habilidades_blandas": HABILIDADES_BLANDAS,
            "niveles_rubrica": [n.__dict__ for n in NIVELES_RUBRICA],
            # Opciones del formulario «¿Cómo quiere su sílabo?».
            "metodologias": sorted(set(indicaciones.METODOLOGIAS.values())),
            "tecnologias": sorted(set(indicaciones.TECNOLOGIAS.values()), key=str.casefold),
            "instrumentos": sorted(set(indicaciones.INSTRUMENTOS.values())),
        }

    def asignatura_dict(a: Asignatura) -> dict:
        try:
            ficha, error = ficha_de(a).model_dump(mode="json"), None
        except ValueError as e:  # ficha extraída de la malla todavía incompleta
            ficha, error = a.ficha, str(e).splitlines()[0]
        return {"id": a.id, "codigo": a.codigo, "nombre": a.nombre, "carrera": a.carrera,
                "nivel": a.nivel, "horas": a.horas, "creditos": a.creditos, "ficha": ficha,
                "ficha_valida": error is None, "error_ficha": error, "origen": a.origen or "ejemplo",
                "revisada": bool(a.revisada), "malla_id": a.malla_id, "avisos": a.avisos or []}

    @app.get("/asignaturas")
    def asignaturas(c: Cont, _: Usuario, carrera: str | None = None) -> list[dict]:
        with c.fabrica() as sesion:
            consulta = select(Asignatura).order_by(Asignatura.carrera, Asignatura.nivel, Asignatura.codigo)
            if carrera:
                consulta = consulta.where(Asignatura.carrera == carrera)
            return [asignatura_dict(a) for a in sesion.scalars(consulta)]

    # --- corpus --------------------------------------------------------------------------

    def documento_dict(c: Contenedor, d: Documento) -> dict:
        return {"id": d.id, "titulo": d.titulo, "tipo": str(d.tipo), "carrera": d.carrera,
                "version": d.version, "fecha_vigencia": d.fecha_vigencia.isoformat(),
                "estado": str(d.estado), "fragmentos": c.recuperador.almacen.contar(d.id),
                "archivo": Path(d.ruta).name}

    @app.get("/documentos")
    def listar_documentos(c: Cont, _: Usuario) -> list[dict]:
        with c.fabrica() as sesion:
            return [documento_dict(c, d) for d in sesion.scalars(select(Documento).order_by(Documento.id))]

    @app.post("/documentos")
    def cargar_documento(
        c: Cont, u: Admin, archivo: Annotated[UploadFile, File()],
        titulo: Annotated[str, Form()], tipo: Annotated[TipoDocumento, Form()],
        carrera: Annotated[str, Form()], version: Annotated[str, Form()],
        fecha_vigencia: Annotated[date, Form()],
    ) -> dict:
        """Registra el documento (con reglas de vigencia) y lo indexa en el mismo paso."""
        meta = con_errores(MetadatosDocumento, titulo=titulo, tipo=tipo, carrera=carrera,
                           version=version, fecha_vigencia=fecha_vigencia)
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / Path(archivo.filename or "documento").name
            with ruta.open("wb") as destino:
                shutil.copyfileobj(archivo.file, destino)
            with c.fabrica() as sesion:
                documento = con_errores(
                    registrar_documento, sesion, ruta, meta, u["id"], c.config.corpus.directorio,
                    tuple(c.config.corpus.extensiones),
                )
                con_errores(procesar_documento, sesion, c.recuperador, documento, c.config)
                sincronizar_vigencia(sesion, c.recuperador)
                sesion.commit()
                datos = documento_dict(c, documento)
        # Los docentes se enteran en el panel de noticias (resumen del agente con RAG).
        datos["noticia"] = c.noticias.documento_publicado(datos["id"], u["id"])
        return datos

    @app.post("/documentos/{documento_id}/indexar")
    def indexar_documento(documento_id: int, c: Cont, _: Admin) -> dict:
        with c.fabrica() as sesion:
            documento = sesion.get(Documento, documento_id)
            if documento is None:
                raise HTTPException(404, "No existe el documento")
            con_errores(procesar_documento, sesion, c.recuperador, documento, c.config)
            sesion.commit()
            return documento_dict(c, documento)

    class CambioDocumento(BaseModel):
        estado: EstadoDocumento

    @app.patch("/documentos/{documento_id}")
    def cambiar_documento(documento_id: int, cambio: CambioDocumento, c: Cont, u: Admin) -> dict:
        with c.fabrica() as sesion:
            anterior = sesion.get(Documento, documento_id)
            estado_previo = anterior.estado if anterior else None
            documento = con_errores(cambiar_estado, sesion, documento_id, cambio.estado)
            sincronizar_vigencia(sesion, c.recuperador)
            sesion.commit()
            datos = documento_dict(c, documento)
        if estado_previo != cambio.estado:
            if cambio.estado == EstadoDocumento.OBSOLETO:
                c.noticias.documento_retirado(documento_id, u["id"])
            else:
                c.noticias.documento_publicado(documento_id, u["id"])
        return datos

    class Busqueda(BaseModel):
        consulta: str
        tipos: list[TipoDocumento] | None = None
        carrera: str | None = None
        solo_vigentes: bool = True
        k: int = 6

    @app.post("/buscar")
    def buscar(b: Busqueda, c: Cont, _: Usuario) -> list[dict]:
        resultados = c.recuperador.buscar(b.consulta, b.tipos, b.carrera, b.solo_vigentes, b.k)
        return [{"cita": r.cita, "puntaje": r.puntaje, "puntaje_lexico": r.puntaje_lexico,
                 "fragmento": r.fragmento.model_dump(mode="json")} for r in resultados]

    @app.get("/fragmentos/{fragmento_id}")
    def fragmento(fragmento_id: str, c: Cont, _: Usuario) -> dict:
        encontrado = c.recuperador.almacen.obtener([fragmento_id]).get(fragmento_id)
        if encontrado is None:
            raise HTTPException(404, "No existe el fragmento")
        return encontrado.model_dump(mode="json")

    # --- sílabos -------------------------------------------------------------------------

    class NuevoSilabo(BaseModel):
        asignatura_id: int
        periodo: str
        datos_generales: dict[str, Any] = {}

    @app.post("/silabos")
    def crear_silabo(n: NuevoSilabo, c: Cont, u: Usuario) -> dict:
        if u["rol"] != Rol.DOCENTE:
            raise HTTPException(403, "Solo un docente crea sílabos")
        silabo_id = con_errores(c.servicio.crear_silabo, u["id"], n.asignatura_id, n.periodo,
                                n.datos_generales)
        con_errores(c.orquestador.iniciar, silabo_id)
        return respuesta_silabo(c, silabo_id)

    @app.get("/silabos")
    def listar_silabos(c: Cont, u: Usuario) -> list[dict]:
        with c.fabrica() as sesion:
            consulta = select(Silabo).order_by(Silabo.id.desc())
            if u["rol"] == Rol.DOCENTE:
                consulta = consulta.where(Silabo.docente_id == u["id"])
            return [
                {"id": s.id, "asignatura": f"{s.asignatura.codigo} {s.asignatura.nombre}",
                 "periodo": s.periodo, "estado": str(s.estado),
                 "aprobadas": sum(1 for x in s.secciones if x.estado == "aprobada"),
                 "secciones": len(s.secciones), "actualizado": s.actualizado.isoformat()}
                for s in sesion.scalars(consulta)
            ]

    @app.get("/silabos/{silabo_id}")
    def ver_silabo(silabo_id: int, c: Cont, u: Usuario) -> dict:
        comprobar_silabo(c, u, silabo_id, escribir=False)
        return respuesta_silabo(c, silabo_id)

    @app.post("/silabos/{silabo_id}/continuar")
    def continuar(silabo_id: int, c: Cont, u: Usuario) -> dict:
        """Retoma el flujo (RF-26): útil tras reiniciar el servidor o cargar documentos."""
        comprobar_silabo(c, u, silabo_id)
        con_errores(c.orquestador.iniciar, silabo_id)
        return respuesta_silabo(c, silabo_id)

    class Indicacion(BaseModel):
        indicacion: str | None = None

    @app.post("/silabos/{silabo_id}/secciones/{clave}/generar")
    def regenerar(silabo_id: int, clave: str, i: Indicacion, c: Cont, u: Usuario) -> dict:
        comprobar_silabo(c, u, silabo_id)
        exigir_pausa_en(c, silabo_id, clave)
        con_errores(c.orquestador.reanudar, silabo_id, {"accion": "regenerar", "indicacion": i.indicacion})
        return respuesta_silabo(c, silabo_id)

    class DecisionEnVivo(BaseModel):
        accion: str = "aprobar"  # aprobar | regenerar
        indicacion: str | None = None
        contenido: dict[str, Any] | None = None

    @app.post("/silabos/{silabo_id}/secciones/{clave}/stream")
    def decidir_en_vivo(silabo_id: int, clave: str, d: DecisionEnVivo, c: Cont, u: Usuario):
        """Aprueba o regenera y transmite en eventos SSE lo que hace el agente hasta la próxima
        pausa: pasos («Buscando evidencia…»), trozos de texto del modelo y el sílabo final."""
        comprobar_silabo(c, u, silabo_id)
        exigir_pausa_en(c, silabo_id, clave)
        if d.accion not in ("aprobar", "regenerar"):
            raise HTTPException(400, "En vivo solo se aprueba o se regenera")
        cola: queue.Queue = queue.Queue()

        def trabajar() -> None:
            c.servicio.oyentes[silabo_id] = cola.put
            try:
                c.orquestador.reanudar(silabo_id, d.model_dump(exclude_none=True))
                cola.put({"tipo": "fin", "silabo": respuesta_silabo(c, silabo_id)})
            except Exception as error:  # noqa: BLE001 — se informa al cliente en el flujo
                cola.put({"tipo": "error", "mensaje": str(error)})
            finally:
                c.servicio.oyentes.pop(silabo_id, None)
                cola.put(None)

        threading.Thread(target=trabajar, daemon=True).start()

        def eventos():
            while (evento := cola.get()) is not None:
                yield f"data: {json.dumps(evento, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(eventos(), media_type="text/event-stream")

    @app.put("/silabos/{silabo_id}/preferencias")
    def preferencias(silabo_id: int, p: indicaciones.Preferencias, c: Cont, u: Usuario) -> dict:
        comprobar_silabo(c, u, silabo_id)
        con_errores(c.servicio.actualizar_preferencias, silabo_id, p.model_dump(mode="json"))
        return respuesta_silabo(c, silabo_id)

    class Edicion(BaseModel):
        contenido: dict[str, Any]

    @app.put("/silabos/{silabo_id}/secciones/{clave}")
    def editar(silabo_id: int, clave: str, e: Edicion, c: Cont, u: Usuario) -> dict:
        comprobar_silabo(c, u, silabo_id)
        exigir_pausa_en(c, silabo_id, clave)
        con_errores(c.orquestador.reanudar, silabo_id, {"accion": "editar", "contenido": e.contenido})
        return respuesta_silabo(c, silabo_id)

    class Aprobacion(BaseModel):
        contenido: dict[str, Any] | None = None

    @app.post("/silabos/{silabo_id}/secciones/{clave}/aprobar")
    def aprobar(silabo_id: int, clave: str, a: Aprobacion, c: Cont, u: Usuario) -> dict:
        comprobar_silabo(c, u, silabo_id)
        exigir_pausa_en(c, silabo_id, clave)
        con_errores(c.orquestador.reanudar, silabo_id, {"accion": "aprobar", "contenido": a.contenido})
        return respuesta_silabo(c, silabo_id)

    @app.post("/silabos/{silabo_id}/secciones/{clave}/reabrir")
    def reabrir(silabo_id: int, clave: str, c: Cont, u: Usuario) -> dict:
        comprobar_silabo(c, u, silabo_id)
        con_errores(c.orquestador.reabrir, silabo_id, clave)
        return respuesta_silabo(c, silabo_id)

    @app.post("/silabos/{silabo_id}/validar")
    def validar(silabo_id: int, c: Cont, u: Usuario) -> dict:
        comprobar_silabo(c, u, silabo_id, escribir=False)
        if c.orquestador.pendiente(silabo_id).get("tipo") == "correccion":
            con_errores(c.orquestador.reanudar, silabo_id, {"accion": "verificar"})
        else:
            con_errores(c.servicio.verificar, silabo_id)
        return respuesta_silabo(c, silabo_id)

    class Descarte(BaseModel):
        justificacion: str

    @app.post("/silabos/{silabo_id}/hallazgos/{hallazgo_id}/descartar")
    def descartar(silabo_id: int, hallazgo_id: int, d: Descarte, c: Cont, u: Usuario) -> dict:
        comprobar_silabo(c, u, silabo_id)
        con_errores(c.servicio.descartar_advertencia, silabo_id, hallazgo_id, d.justificacion)
        return respuesta_silabo(c, silabo_id)

    @app.post("/silabos/{silabo_id}/exportar")
    def exportar(silabo_id: int, c: Cont, u: Usuario, formato: str = "docx",
                 borrador: bool = False) -> FileResponse:
        comprobar_silabo(c, u, silabo_id)
        ruta = con_errores(c.servicio.exportar, silabo_id, formato, borrador)
        tipo = ("application/pdf" if formato == "pdf" else
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        return FileResponse(ruta, media_type=tipo, filename=ruta.name)

    @app.get("/metricas/export")
    def metricas(c: Cont, u: Usuario) -> FileResponse:
        if u["rol"] == Rol.DOCENTE:
            raise HTTPException(403, "Las métricas son para el administrador y el evaluador")
        with c.fabrica() as sesion:
            ruta_csv, _ = exportar_eventos(sesion, c.config.telemetria.directorio)
        return FileResponse(ruta_csv, media_type="text/csv", filename=ruta_csv.name)

    from syllabusai.web.rutas import registrar_rutas_web

    registrar_rutas_web(app, Cont, Usuario, Admin, comprobar_silabo, con_errores, asignatura_dict)
    return app


app = crear_app()
