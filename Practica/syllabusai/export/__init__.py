"""Exportación del sílabo al formato institucional en DOCX y PDF (RF-40 a RF-43)."""

import re
import shutil
import subprocess
from pathlib import Path

from syllabusai.config import ConfigExportacion
from syllabusai.export import documento, render_docx, render_pdf


class ErrorExportacion(RuntimeError):
    pass


def _nombre_base(datos: dict) -> str:
    ident = datos["secciones"].get("identificacion", {})
    base = f"silabo_{ident.get('codigo', 'PF')}_{datos['silabo']['periodo']}_{datos['silabo']['id']}"
    if datos.get("borrador"):
        base += "_borrador"
    return re.sub(r"[^\w.-]+", "_", base)


def exportar_silabo(datos: dict, formato: str, config: ConfigExportacion) -> Path:
    if formato not in ("docx", "pdf"):
        raise ErrorExportacion(f"Formato de exportación no admitido: {formato}")
    directorio = Path(config.directorio)
    base = _nombre_base(datos)
    elementos = documento.construir(datos)
    ruta_docx = render_docx.renderizar(elementos, directorio / f"{base}.docx")
    render_docx.renderizar(documento.construir_trazabilidad(datos), directorio / f"{base}_trazabilidad.docx")
    if formato == "docx":
        return ruta_docx

    soffice = config.soffice or shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        resultado = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(directorio), str(ruta_docx)],
            capture_output=True, timeout=120, check=False,
        )
        ruta_pdf = directorio / f"{base}.pdf"
        if resultado.returncode == 0 and ruta_pdf.exists():
            return ruta_pdf
    return render_pdf.renderizar(elementos, directorio / f"{base}.pdf")
