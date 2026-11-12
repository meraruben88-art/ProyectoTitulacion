"""Vigía: mantiene las noticias al día sin que nadie tenga que pedirlo.

Cada cierto tiempo (configuración `noticias.intervalo_min`) revisa:

- las fuentes externas registradas por el administrador (canales RSS o páginas de la
  universidad y de otras universidades): una entrada RSS nueva o un cambio en el texto de una
  página genera una noticia, que el agente relaciona con el corpus;
- la bandeja de documentos (`data/bandeja`): un PDF o DOCX que se deja allí se registra, se
  indexa y se anuncia solo. Si junto al archivo hay un `.yaml` con el mismo nombre, sus
  metadatos (título, tipo, carrera, versión, fecha de vigencia) se usan para registrarlo.
"""

import hashlib
import html
import logging
import re
import shutil
import threading
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from sqlalchemy import select

from syllabusai.db.modelos import FuenteNoticias, Rol, TipoDocumento, Usuario
from syllabusai.esquemas import MetadatosDocumento

log = logging.getLogger("syllabusai.vigia")
_ETIQUETAS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.DOTALL | re.IGNORECASE)


def texto_visible(contenido: str) -> str:
    """Texto legible de una página HTML, para comparar versiones."""
    texto = html.unescape(_ETIQUETAS.sub(" ", contenido))
    lineas = [" ".join(linea.split()) for linea in texto.splitlines()]
    return "\n".join(linea for linea in lineas if len(linea) > 2)


def entradas_rss(contenido: str) -> list[dict]:
    """Entradas de un canal RSS 2.0 o Atom: identificador, título, enlace y resumen."""
    raiz = ET.fromstring(contenido)
    entradas = []
    for item in raiz.iter():
        etiqueta = item.tag.split("}")[-1]
        if etiqueta not in ("item", "entry"):
            continue
        campos = {c.tag.split("}")[-1]: c for c in item}
        enlace = campos.get("link")
        url = (enlace.get("href") or enlace.text or "") if enlace is not None else ""
        titulo = (campos["title"].text or "").strip() if "title" in campos else ""
        # Un elemento sin hijos es «falso» en ElementTree: se elige el primero que exista.
        resumen_el = next((campos[k] for k in ("description", "summary", "content") if k in campos), None)
        resumen = texto_visible(resumen_el.text or "") if resumen_el is not None else ""
        guid = next((campos[k] for k in ("guid", "id") if k in campos), None)
        entradas.append({"id": (guid.text if guid is not None else None) or url or titulo,
                         "titulo": titulo, "url": url, "resumen": resumen})
    return entradas


class Vigia:
    def __init__(self, contenedor, noticias, cliente_http: httpx.Client | None = None):
        self.c = contenedor
        self.noticias = noticias
        self.http = cliente_http or httpx.Client(timeout=20.0, follow_redirects=True,
                                                 headers={"User-Agent": "SyllabusAI-vigia/1.0"})
        self._detener = threading.Event()
        self._hilo: threading.Thread | None = None
        self.ultima_ronda: datetime | None = None

    # --- ciclo ---------------------------------------------------------------------------

    def iniciar(self) -> None:
        if self._hilo is None and self.c.config.noticias.activo:
            self._hilo = threading.Thread(target=self._ciclo, name="vigia", daemon=True)
            self._hilo.start()

    def detener(self) -> None:
        self._detener.set()

    def _ciclo(self) -> None:
        while not self._detener.is_set():
            try:
                self.ronda()
            except Exception:  # el vigía no debe caerse por una fuente rota
                log.exception("La ronda del vigía falló")
            self._detener.wait(self.c.config.noticias.intervalo_min * 60)

    def ronda(self) -> list[dict]:
        """Una revisión completa. Devuelve las noticias publicadas."""
        publicadas = self.revisar_bandeja()
        with self.c.fabrica() as sesion:
            fuentes = [f.id for f in sesion.scalars(select(FuenteNoticias).where(FuenteNoticias.activa))]
        for fuente_id in fuentes:
            publicadas += self.revisar_fuente(fuente_id)
        self.ultima_ronda = datetime.now(UTC)
        return publicadas

    # --- fuentes externas ----------------------------------------------------------------

    def revisar_fuente(self, fuente_id: int) -> list[dict]:
        with self.c.fabrica() as sesion:
            fuente = sesion.get(FuenteNoticias, fuente_id)
            url, tipo, nombre, carrera = fuente.url, fuente.tipo, fuente.nombre, fuente.carrera
            vistos, hash_previo = list(fuente.vistos or []), fuente.ultimo_hash
        publicadas: list[dict] = []
        error = None
        nuevo_hash = hash_previo
        try:
            r = self.http.get(url)
            r.raise_for_status()
            if tipo == "rss":
                entradas = entradas_rss(r.text)
                primera_vez = not vistos
                for e in entradas:
                    if e["id"] in vistos:
                        continue
                    vistos.append(e["id"])
                    # La primera revisión solo registra lo que ya existía; no inunda el panel.
                    if not primera_vez:
                        publicadas.append(self.noticias.cambio_externo(
                            nombre, e["titulo"] or nombre, e["resumen"] or e["titulo"], e["url"] or url,
                            carrera))
            else:
                texto = texto_visible(r.text)
                nuevo_hash = hashlib.sha256(texto.encode()).hexdigest()
                if hash_previo and nuevo_hash != hash_previo:
                    publicadas.append(self.noticias.cambio_externo(
                        nombre, f"Cambió la página «{nombre}»", texto[:2500], url, carrera))
        except (httpx.HTTPError, ET.ParseError) as e:
            error = f"{type(e).__name__}: {e}"[:500]
        with self.c.fabrica() as sesion:
            fuente = sesion.get(FuenteNoticias, fuente_id)
            fuente.vistos = vistos[-500:]
            fuente.ultimo_hash = nuevo_hash
            fuente.ultima_revision = datetime.now(UTC)
            fuente.ultimo_error = error
            sesion.commit()
        return publicadas

    # --- bandeja de documentos -----------------------------------------------------------

    def revisar_bandeja(self) -> list[dict]:
        from syllabusai.ingest.pipeline import procesar_documento, sincronizar_vigencia
        from syllabusai.ingest.registro import ErrorRegistro, registrar_documento

        bandeja = self.c.config.noticias.bandeja
        if bandeja is None:
            return []
        bandeja.mkdir(parents=True, exist_ok=True)
        procesados = bandeja / "procesados"
        publicadas = []
        for archivo in sorted(bandeja.iterdir()):
            if archivo.suffix.lower() not in tuple(self.c.config.corpus.extensiones):
                continue
            meta = self._metadatos(archivo)
            with self.c.fabrica() as sesion:
                admin = sesion.scalar(select(Usuario).where(Usuario.rol == Rol.ADMIN_CORPUS).order_by(Usuario.id))
                if admin is None:
                    return publicadas
                try:
                    doc = registrar_documento(sesion, archivo, meta, admin.id, self.c.config.corpus.directorio,
                                              tuple(self.c.config.corpus.extensiones))
                    procesar_documento(sesion, self.c.recuperador, doc, self.c.config)
                    sincronizar_vigencia(sesion, self.c.recuperador)
                    sesion.commit()
                    doc_id = doc.id
                except (ErrorRegistro, ValueError) as error:
                    log.warning("No se pudo ingerir %s de la bandeja: %s", archivo.name, error)
                    sesion.rollback()
                    doc_id = None
            procesados.mkdir(exist_ok=True)
            shutil.move(str(archivo), procesados / archivo.name)
            lateral = archivo.with_suffix(".yaml")
            if lateral.exists():
                shutil.move(str(lateral), procesados / lateral.name)
            if doc_id is not None:
                publicadas.append(self.noticias.documento_publicado(doc_id))
        return publicadas

    @staticmethod
    def _metadatos(archivo: Path) -> MetadatosDocumento:
        lateral = archivo.with_suffix(".yaml")
        datos = yaml.safe_load(lateral.read_text(encoding="utf-8")) if lateral.exists() else {}
        datos = datos or {}
        hoy = datetime.now(UTC).date()
        return MetadatosDocumento(
            titulo=datos.get("titulo") or archivo.stem.replace("_", " "),
            tipo=TipoDocumento(datos.get("tipo", "normativa")),
            carrera=datos.get("carrera", "TODAS"),
            version=str(datos.get("version") or hoy.isoformat()),
            fecha_vigencia=datos.get("fecha_vigencia") or hoy,
        )
