"""Rutas de la interfaz web (prefijo /web) y archivos estáticos de la página.

La página es una aplicación de una sola vista (`static/index.html`) que usa estas rutas y las de
la API de sílabos (`/silabos`, `/asignaturas`, `/documentos`…) con la cookie de sesión. Los
permisos son los mismos: el administrador gestiona cuentas, corpus, mallas y fuentes de
noticias; cada docente ve y edita solo sus sílabos.
"""

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select

from syllabusai.db.modelos import (
    Asignatura,
    Documento,
    FuenteNoticias,
    Malla,
    Rol,
    Silabo,
    Usuario,
)
from syllabusai.formato.esquemas import ESQUEMAS
from syllabusai.seguridad import (
    abrir_sesion,
    autenticar,
    cerrar_sesion,
    contrasena_temporal,
    crear_usuario,
    hash_contrasena,
    verificar_contrasena,
)

ESTATICOS = Path(__file__).with_name("static")

# Campos oficiales del sílabo (Propuesta 2026: importar y bloquear). En el documento final el
# docente puede desbloquearlos, y la verificación señala el cambio.
OFICIALES = {
    "identificacion": ["*"],
    "resultados_aprendizaje": ["codigo", "enunciado"],
    "contenidos": ["contenidos_minimos"],
    "planeacion_momentos": ["numero", "semanas", "ra", "horas_contacto", "horas_practicas",
                            "horas_autonomas", "peso"],
    "evaluacion": ["momento", "ra", "peso"],
}


def usuario_dict(u: Usuario, silabos: int = 0) -> dict:
    return {"id": u.id, "nombre": u.nombre, "correo": u.correo, "rol": str(u.rol),
            "activo": u.activo is not False, "carrera": u.carrera, "silabos": silabos}


def malla_dict(m: Malla) -> dict:
    asignaturas = list(m.asignaturas)
    return {"id": m.id, "carrera": m.carrera, "nombre": m.nombre, "archivo": Path(m.archivo).name,
            "documento_id": m.documento_id, "paginas": m.paginas, "estado": m.estado,
            "avisos": m.avisos or [], "asignaturas": len(asignaturas),
            "revisadas": sum(1 for a in asignaturas if a.revisada),
            "niveles": sorted({a.nivel for a in asignaturas}), "fecha_carga": m.fecha_carga.isoformat()}


def registrar_rutas_web(app: FastAPI, Cont, Usuario_, Admin, comprobar_silabo, con_errores,
                        asignatura_dict) -> None:
    # --- sesión --------------------------------------------------------------------------

    class Credenciales(BaseModel):
        correo: str
        clave: str

    @app.post("/web/login")
    def login(cred: Credenciales, response: Response, c: Cont) -> dict:
        with c.fabrica() as sesion:
            usuario = autenticar(sesion, cred.correo, cred.clave)
            if usuario is None:
                raise HTTPException(401, "Correo o contraseña incorrectos, o la cuenta está desactivada")
            token = abrir_sesion(sesion, usuario, c.config.web.sesion_horas)
            sesion.commit()
            datos = usuario_dict(usuario)
        response.set_cookie(c.config.web.cookie, token, httponly=True, samesite="lax",
                            secure=c.config.web.cookie_segura,
                            max_age=int(c.config.web.sesion_horas * 3600))
        return datos

    @app.post("/web/logout")
    def logout(request: Request, response: Response, c: Cont) -> dict:
        token = request.cookies.get(c.config.web.cookie)
        if token:
            with c.fabrica() as sesion:
                cerrar_sesion(sesion, token)
                sesion.commit()
        response.delete_cookie(c.config.web.cookie)
        return {"ok": True}

    @app.get("/web/yo")
    def yo(u: Usuario_) -> dict:
        return u

    class CambioClave(BaseModel):
        actual: str
        nueva: str

    @app.post("/web/clave")
    def cambiar_clave(cambio: CambioClave, c: Cont, u: Usuario_) -> dict:
        if len(cambio.nueva) < 8:
            raise HTTPException(400, "La contraseña nueva debe tener al menos 8 caracteres")
        with c.fabrica() as sesion:
            usuario = sesion.get(Usuario, u["id"])
            if not verificar_contrasena(cambio.actual, usuario.hash_contrasena):
                raise HTTPException(400, "La contraseña actual no es correcta")
            usuario.hash_contrasena = hash_contrasena(cambio.nueva)
            sesion.commit()
        return {"ok": True}

    # --- estado del sistema --------------------------------------------------------------

    @app.get("/web/estado")
    def estado(c: Cont, _: Usuario_) -> dict:
        llm, emb = c.config.llm, c.config.embeddings
        destino = ("NVIDIA Build (API alojada)" if "integrate.api.nvidia.com" in llm.url else
                   "NIM propio (NVIDIA Brev u otro servidor)") if llm.proveedor != "simulado" else "simulado"
        with c.fabrica() as sesion:
            documentos = sesion.scalar(select(func.count()).select_from(Documento))
        return {"llm": {"proveedor": llm.proveedor, "modelo": c.llm.nombre, "destino": destino,
                        "url": llm.url if llm.proveedor != "simulado" else None},
                "embeddings": {"proveedor": emb.proveedor,
                               "modelo": emb.modelo if emb.proveedor != "ninguno" else None},
                "documentos": documentos, "formato": f"{c.formato.nombre} {c.formato.version}",
                "vigia_min": c.config.noticias.intervalo_min}

    @app.post("/web/modelo/probar")
    def probar_modelo(c: Cont, _: Admin) -> dict:
        """Hace una llamada mínima al modelo configurado para comprobar la clave y la URL."""
        from syllabusai.agent.harness import ErrorHarness, Harness
        from syllabusai.noticias.servicio import SalidaRespuesta

        mensajes = [{"role": "system", "content": "Responde solo con JSON."},
                    {"role": "user", "content": 'Devuelve {"contenido": {"respuesta": "ok", "puntos": []}, '
                                                '"fuentes": [], "abstencion": null, "notas": null}.'}]
        try:
            r = Harness(c.llm).generar("respuesta", mensajes, SalidaRespuesta,
                                       contexto={"fragmentos": [{"titulo": "prueba", "version": "1",
                                                                 "pagina": 1, "texto": "ok", "id": "p"}]})
        except ErrorHarness as error:
            raise HTTPException(502, str(error)) from error
        return {"ok": True, "modelo": r.respuesta.modelo, "latencia_ms": round(r.respuesta.latencia_ms),
                "ttft_ms": r.respuesta.ttft_ms and round(r.respuesta.ttft_ms)}

    # --- cuentas (administrador) ---------------------------------------------------------

    @app.get("/web/usuarios")
    def usuarios(c: Cont, _: Admin) -> list[dict]:
        with c.fabrica() as sesion:
            cuentas = {r[0]: r[1] for r in sesion.execute(
                select(Silabo.docente_id, func.count()).group_by(Silabo.docente_id))}
            return [usuario_dict(u, cuentas.get(u.id, 0))
                    for u in sesion.scalars(select(Usuario).order_by(Usuario.rol, Usuario.nombre))]

    class NuevaCuenta(BaseModel):
        nombre: str
        correo: str
        rol: Rol = Rol.DOCENTE
        carrera: str | None = None
        clave: str | None = None

    def _crear_cuenta(sesion, n: NuevaCuenta) -> dict:
        clave = n.clave or contrasena_temporal()
        usuario = con_errores(crear_usuario, sesion, n.nombre.strip(), n.correo, clave, n.rol, n.carrera)
        return usuario_dict(usuario) | {"clave_temporal": None if n.clave else clave}

    @app.post("/web/usuarios")
    def crear_cuenta(n: NuevaCuenta, c: Cont, _: Admin) -> dict:
        if "@" not in n.correo or not n.nombre.strip():
            raise HTTPException(400, "Indique nombre y correo válidos")
        with c.fabrica() as sesion:
            datos = _crear_cuenta(sesion, n)
            sesion.commit()
            return datos

    class Lote(BaseModel):
        texto: str  # una cuenta por línea: «Nombre; correo; carrera»
        carrera: str | None = None

    @app.post("/web/usuarios/lote")
    def crear_lote(lote: Lote, c: Cont, _: Admin) -> dict:
        creadas, errores = [], []
        with c.fabrica() as sesion:
            for linea in lote.texto.splitlines():
                partes = [p.strip() for p in linea.replace("\t", ";").replace(",", ";").split(";")]
                if len(partes) < 2 or not partes[0]:
                    if linea.strip():
                        errores.append(f"«{linea.strip()}»: use «Nombre; correo; carrera»")
                    continue
                try:
                    creadas.append(_crear_cuenta(sesion, NuevaCuenta(
                        nombre=partes[0], correo=partes[1],
                        carrera=(partes[2] if len(partes) > 2 and partes[2] else lote.carrera))))
                except HTTPException as error:
                    errores.append(f"{partes[1]}: {error.detail}")
            sesion.commit()
        return {"creadas": creadas, "errores": errores}

    class CambioCuenta(BaseModel):
        nombre: str | None = None
        activo: bool | None = None
        rol: Rol | None = None
        carrera: str | None = None
        restablecer_clave: bool = False

    @app.patch("/web/usuarios/{usuario_id}")
    def cambiar_cuenta(usuario_id: int, cambio: CambioCuenta, c: Cont, admin: Admin) -> dict:
        with c.fabrica() as sesion:
            usuario = sesion.get(Usuario, usuario_id)
            if usuario is None:
                raise HTTPException(404, "No existe la cuenta")
            if usuario.id == admin["id"] and (cambio.activo is False or (cambio.rol and cambio.rol != Rol.ADMIN_CORPUS)):
                raise HTTPException(400, "No puede desactivar ni quitarse el rol de administrador a sí mismo")
            if cambio.nombre:
                usuario.nombre = cambio.nombre.strip()
            if cambio.activo is not None:
                usuario.activo = cambio.activo
            if cambio.rol is not None:
                usuario.rol = cambio.rol
            if cambio.carrera is not None:
                usuario.carrera = cambio.carrera or None
            clave = None
            if cambio.restablecer_clave:
                clave = contrasena_temporal()
                usuario.hash_contrasena = hash_contrasena(clave)
            sesion.commit()
            return usuario_dict(usuario) | {"clave_temporal": clave}

    # --- mallas --------------------------------------------------------------------------

    @app.get("/web/mallas")
    def mallas(c: Cont, _: Usuario_) -> list[dict]:
        with c.fabrica() as sesion:
            return [malla_dict(m) for m in sesion.scalars(select(Malla).order_by(Malla.nombre))]

    @app.get("/web/mallas/{malla_id}")
    def malla(malla_id: int, c: Cont, _: Usuario_) -> dict:
        with c.fabrica() as sesion:
            m = sesion.get(Malla, malla_id)
            if m is None:
                raise HTTPException(404, "No existe la malla")
            return malla_dict(m) | {"lista": [asignatura_dict(a) for a in sorted(
                m.asignaturas, key=lambda a: (a.nivel, a.codigo))]}

    @app.get("/web/mallas/{malla_id}/pdf")
    def malla_pdf(malla_id: int, c: Cont, _: Usuario_) -> FileResponse:
        with c.fabrica() as sesion:
            m = sesion.get(Malla, malla_id)
            if m is None:
                raise HTTPException(404, "No existe la malla")
            ruta = Path(m.documento.ruta if m.documento else m.archivo)
        if not ruta.exists():
            raise HTTPException(404, "El archivo de la malla no está en el servidor")
        return FileResponse(ruta, media_type="application/pdf",
                            headers={"Content-Disposition": f'inline; filename="{ruta.name}"'})

    def _importar(c, rutas: list[Path], admin_id: int, reextraer: bool) -> list[dict]:
        from syllabusai.ingest.importar_mallas import importar_malla

        resultados = []
        for ruta in rutas:
            with c.fabrica() as sesion:
                m, extraida = con_errores(importar_malla, sesion, c, ruta, admin_id, reextraer)
                sesion.commit()
                datos = malla_dict(m)
            if extraida is not None:
                datos["noticia"] = c.noticias.malla_importada(
                    datos["nombre"], datos["carrera"], datos["asignaturas"], datos["documento_id"],
                    datos["avisos"], admin_id)
            resultados.append(datos)
        return resultados

    @app.post("/web/mallas/importar-carpeta")
    def importar_carpeta(c: Cont, u: Admin, reextraer: bool = False) -> list[dict]:
        rutas = sorted(Path(c.config.mallas.directorio).glob("*.pdf"))
        if not rutas:
            raise HTTPException(404, f"No hay PDF en {c.config.mallas.directorio}")
        return _importar(c, rutas, u["id"], reextraer)

    @app.post("/web/mallas")
    def subir_malla(c: Cont, u: Admin, archivo: Annotated[UploadFile, File()]) -> list[dict]:
        nombre = Path(archivo.filename or "malla.pdf").name
        if not nombre.lower().endswith(".pdf"):
            raise HTTPException(400, "La malla debe ser un PDF del CES")
        destino = Path(c.config.mallas.directorio) / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("wb") as salida:
            shutil.copyfileobj(archivo.file, salida)
        return _importar(c, [destino], u["id"], False)

    @app.post("/web/mallas/{malla_id}/publicar")
    def publicar_malla(malla_id: int, c: Cont, _: Admin) -> dict:
        with c.fabrica() as sesion:
            m = sesion.get(Malla, malla_id)
            if m is None:
                raise HTTPException(404, "No existe la malla")
            m.estado = "publicada"
            sesion.commit()
            return malla_dict(m)

    class FichaEditada(BaseModel):
        codigo: str | None = None
        nombre: str | None = None
        nivel: int | None = None
        carrera: str | None = None
        ficha: dict[str, Any] | None = None
        revisada: bool | None = None

    @app.put("/web/asignaturas/{asignatura_id}")
    def editar_asignatura(asignatura_id: int, f: FichaEditada, c: Cont, _: Admin) -> dict:
        from syllabusai.esquemas import FichaCurricular

        with c.fabrica() as sesion:
            a = sesion.get(Asignatura, asignatura_id)
            if a is None:
                raise HTTPException(404, "No existe la asignatura")
            for campo in ("codigo", "nombre", "nivel", "carrera"):
                valor = getattr(f, campo)
                if valor not in (None, ""):
                    setattr(a, campo, valor)
            if f.ficha is not None:
                ficha = {k: v for k, v in f.ficha.items()}
                ficha["resultados_aprendizaje"] = [
                    {"codigo": f"RA{i}", "enunciado": r["enunciado"].strip()}
                    for i, r in enumerate([r for r in ficha.get("resultados_aprendizaje", [])
                                           if str(r.get("enunciado", "")).strip()], start=1)
                ]
                ficha["contenidos_minimos"] = [x.strip() for x in ficha.get("contenidos_minimos", []) if str(x).strip()]
                a.ficha = ficha
                a.horas = int(ficha.get("horas_contacto", 0)) + int(ficha.get("horas_practicas", 0)) + int(
                    ficha.get("horas_autonomas", 0))
            if f.revisada is not None:
                if f.revisada:
                    try:
                        FichaCurricular.model_validate(a.ficha)
                    except ValueError as error:
                        raise HTTPException(400, f"La ficha todavía no es válida: {str(error)[:400]}") from error
                    a.avisos = []
                a.revisada = f.revisada
            if a.origen is None:
                a.origen = "manual"
            sesion.commit()
            return asignatura_dict(a)

    class NuevaAsignatura(BaseModel):
        codigo: str
        nombre: str
        carrera: str
        nivel: int
        malla_id: int | None = None

    @app.post("/web/asignaturas")
    def crear_asignatura(n: NuevaAsignatura, c: Cont, _: Admin) -> dict:
        with c.fabrica() as sesion:
            if sesion.scalar(select(Asignatura).where(Asignatura.codigo == n.codigo)) is not None:
                raise HTTPException(400, f"Ya existe la asignatura {n.codigo}")
            a = Asignatura(codigo=n.codigo.strip(), nombre=n.nombre.strip(), carrera=n.carrera, nivel=n.nivel,
                           horas=0, creditos=None, prerrequisitos=[], malla_id=n.malla_id, origen="manual",
                           revisada=False, avisos=["Asignatura registrada a mano: complete su ficha."],
                           ficha={"facultad": c.formato.facultad, "modalidad": "Presencial", "horas_contacto": 0,
                                  "horas_practicas": 0, "horas_autonomas": 0, "resultados_aprendizaje": [],
                                  "contenidos_minimos": []})
            sesion.add(a)
            sesion.commit()
            return asignatura_dict(a)

    # --- noticias ------------------------------------------------------------------------

    @app.get("/web/noticias")
    def noticias(c: Cont, u: Usuario_, despues_de: int | None = None, limite: int = 40) -> list[dict]:
        carrera = u.get("carrera") if u["rol"] == Rol.DOCENTE else None
        return c.noticias.listar(carrera, min(limite, 100), despues_de)

    class NoticiaManual(BaseModel):
        titulo: str
        cuerpo: str
        categoria: str = "aviso"
        carrera: str = "TODAS"
        importante: bool = False

    @app.post("/web/noticias")
    def publicar_noticia(n: NoticiaManual, c: Cont, u: Admin) -> dict:
        if not n.titulo.strip() or not n.cuerpo.strip():
            raise HTTPException(400, "La noticia necesita título y texto")
        return c.noticias.publicar_manual(n.titulo.strip(), n.cuerpo.strip(), n.categoria, n.carrera,
                                          n.importante, u["id"])

    @app.delete("/web/noticias/{noticia_id}")
    def borrar_noticia(noticia_id: int, c: Cont, _: Admin) -> dict:
        c.noticias.eliminar(noticia_id)
        return {"ok": True}

    class Pregunta(BaseModel):
        pregunta: str

    @app.post("/web/noticias/preguntar")
    def preguntar(p: Pregunta, c: Cont, u: Usuario_) -> dict:
        if len(p.pregunta.strip()) < 4:
            raise HTTPException(400, "Escriba una pregunta")
        return c.noticias.preguntar(p.pregunta.strip(), u.get("carrera"))

    # --- fuentes externas de noticias ----------------------------------------------------

    def fuente_dict(f: FuenteNoticias) -> dict:
        return {"id": f.id, "nombre": f.nombre, "url": f.url, "tipo": f.tipo, "carrera": f.carrera,
                "activa": f.activa, "ultima_revision": f.ultima_revision.isoformat() if f.ultima_revision else None,
                "ultimo_error": f.ultimo_error}

    @app.get("/web/fuentes")
    def fuentes(c: Cont, _: Admin) -> list[dict]:
        with c.fabrica() as sesion:
            return [fuente_dict(f) for f in sesion.scalars(select(FuenteNoticias).order_by(FuenteNoticias.nombre))]

    class NuevaFuente(BaseModel):
        nombre: str
        url: str
        tipo: str = "pagina"
        carrera: str = "TODAS"

    @app.post("/web/fuentes")
    def crear_fuente(n: NuevaFuente, c: Cont, _: Admin) -> dict:
        if not n.url.startswith(("http://", "https://")):
            raise HTTPException(400, "La dirección debe empezar con http:// o https://")
        if n.tipo not in ("rss", "pagina"):
            raise HTTPException(400, "El tipo es «rss» o «pagina»")
        with c.fabrica() as sesion:
            if sesion.scalar(select(FuenteNoticias).where(FuenteNoticias.url == n.url)):
                raise HTTPException(400, "Esa fuente ya está registrada")
            f = FuenteNoticias(nombre=n.nombre.strip(), url=n.url.strip(), tipo=n.tipo, carrera=n.carrera,
                               activa=True, vistos=[])
            sesion.add(f)
            sesion.commit()
            fuente_id = f.id
        from syllabusai.noticias.vigia import Vigia

        Vigia(c, c.noticias).revisar_fuente(fuente_id)  # línea base: lo que ya existe no es noticia
        with c.fabrica() as sesion:
            return fuente_dict(sesion.get(FuenteNoticias, fuente_id))

    @app.delete("/web/fuentes/{fuente_id}")
    def borrar_fuente(fuente_id: int, c: Cont, _: Admin) -> dict:
        with c.fabrica() as sesion:
            f = sesion.get(FuenteNoticias, fuente_id)
            if f is not None:
                sesion.delete(f)
                sesion.commit()
        return {"ok": True}

    @app.post("/web/fuentes/revisar")
    def revisar_ahora(c: Cont, _: Admin) -> dict:
        from syllabusai.noticias.vigia import Vigia

        publicadas = Vigia(c, c.noticias).ronda()
        return {"publicadas": len(publicadas), "fecha": datetime.now(UTC).isoformat()}

    # --- PIS -----------------------------------------------------------------------------

    @app.get("/web/silabos/{silabo_id}/pis")
    def ver_pis(silabo_id: int, c: Cont, u: Usuario_) -> dict:
        comprobar_silabo(c, u, silabo_id, escribir=False)
        return con_errores(c.pis.obtener, silabo_id)

    class PedidoPIS(BaseModel):
        indicacion: str | None = None
        parte: str | None = None

    @app.post("/web/silabos/{silabo_id}/pis/generar")
    def generar_pis(silabo_id: int, p: PedidoPIS, c: Cont, u: Usuario_) -> dict:
        comprobar_silabo(c, u, silabo_id)
        return con_errores(c.pis.generar, silabo_id, (p.indicacion or "").strip() or None, p.parte or None)

    class EdicionPIS(BaseModel):
        contenido: dict[str, Any]

    @app.put("/web/silabos/{silabo_id}/pis")
    def guardar_pis(silabo_id: int, e: EdicionPIS, c: Cont, u: Usuario_) -> dict:
        comprobar_silabo(c, u, silabo_id)
        return con_errores(c.pis.guardar, silabo_id, e.contenido)

    # --- documento final editable --------------------------------------------------------

    @app.get("/web/silabos/{silabo_id}/documento")
    def documento(silabo_id: int, c: Cont, u: Usuario_) -> dict:
        comprobar_silabo(c, u, silabo_id, escribir=False)
        estado = c.servicio.estado(silabo_id)
        with c.fabrica() as sesion:
            silabo = sesion.get(Silabo, silabo_id)
            contenidos = {s.clave: c.servicio._contenido_actual(s) for s in silabo.secciones}
        return {"silabo": {k: estado[k] for k in ("id", "estado", "periodo", "asignatura")},
                "secciones": [{"clave": s["clave"], "titulo": s["titulo"], "estado": s["estado"],
                               "contenido": contenidos[s["clave"]],
                               "esquema": ESQUEMAS[s["clave"]].model_json_schema(),
                               "oficiales": OFICIALES.get(s["clave"], [])}
                              for s in estado["secciones"]],
                "hallazgos": estado["hallazgos"]}

    class DocumentoEditado(BaseModel):
        secciones: dict[str, dict[str, Any]]

    @app.put("/web/silabos/{silabo_id}/documento")
    def guardar_documento(silabo_id: int, d: DocumentoEditado, c: Cont, u: Usuario_) -> dict:
        comprobar_silabo(c, u, silabo_id)
        if c.orquestador.pendiente(silabo_id).get("tipo") == "revision_seccion":
            raise HTTPException(409, "Termine primero la revisión con el agente; luego edite el documento final")
        cambios = con_errores(c.servicio.guardar_documento, silabo_id, d.secciones)
        return cambios | {"hallazgos": c.servicio.estado(silabo_id)["hallazgos"]}

    # --- subida de documentos con metadatos sugeridos ------------------------------------

    @app.post("/web/documentos/vista-previa")
    def vista_previa(c: Cont, _: Admin, archivo: Annotated[UploadFile, File()]) -> dict:
        """Primeras líneas del documento, para que el administrador confirme el título."""
        from syllabusai.ingest.extraccion import extraer

        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / Path(archivo.filename or "documento").name
            with ruta.open("wb") as salida:
                shutil.copyfileobj(archivo.file, salida)
            bloques = con_errores(extraer, ruta)
        titulos = [b.texto for b in bloques if b.nivel_titulo][:5]
        return {"titulo_sugerido": (titulos[0] if titulos else Path(archivo.filename or "").stem)[:200],
                "titulos": titulos, "bloques": len(bloques)}

    # --- página --------------------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    @app.get("/", include_in_schema=False)
    def inicio() -> FileResponse:
        return FileResponse(ESTATICOS / "index.html", headers={"Cache-Control": "no-cache"})
