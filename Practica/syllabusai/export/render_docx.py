"""Renderizador DOCX del documento lógico (python-docx)."""

from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from syllabusai.export.documento import Elemento, Parrafo, Tabla, Titulo

COLOR_INSTITUCIONAL = RGBColor(0x3B, 0x1E, 0x6E)  # morado del logo UTI
FONDO_ENCABEZADO = "E8E2F2"
ANCHO_UTIL_CM = 17.0


def _sombrear(celda, color: str) -> None:
    propiedades = celda._tc.get_or_add_tcPr()
    sombra = OxmlElement("w:shd")
    sombra.set(qn("w:val"), "clear")
    sombra.set(qn("w:color"), "auto")
    sombra.set(qn("w:fill"), color)
    propiedades.append(sombra)


def _escribir_celda(celda, texto: str, negrita: bool = False) -> None:
    celda.text = ""
    lineas = texto.split("\n")
    parrafo = celda.paragraphs[0]
    for i, linea in enumerate(lineas):
        if i:
            parrafo = celda.add_paragraph()
        corrida = parrafo.add_run(linea)
        corrida.bold = negrita
        corrida.font.size = Pt(9)
        parrafo.paragraph_format.space_after = Pt(1)


def renderizar(elementos: list[Elemento], ruta: Path) -> Path:
    doc = Document()
    seccion = doc.sections[0]
    seccion.orientation = WD_ORIENT.PORTRAIT
    seccion.page_width, seccion.page_height = Cm(21.0), Cm(29.7)
    for margen in ("left_margin", "right_margin"):
        setattr(seccion, margen, Cm(2.0))
    seccion.top_margin = seccion.bottom_margin = Cm(2.0)
    estilo = doc.styles["Normal"]
    estilo.font.name = "Arial"
    estilo.font.size = Pt(10)

    for elemento in elementos:
        if isinstance(elemento, Titulo):
            if elemento.nivel == 0:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                corrida = p.add_run(elemento.texto)
                corrida.bold = True
                corrida.font.size = Pt(13)
                corrida.font.color.rgb = COLOR_INSTITUCIONAL
            else:
                encabezado = doc.add_heading(elemento.texto, level=elemento.nivel)
                for corrida in encabezado.runs:
                    corrida.font.color.rgb = COLOR_INSTITUCIONAL
        elif isinstance(elemento, Parrafo):
            p = doc.add_paragraph()
            corrida = p.add_run(elemento.texto)
            corrida.italic = elemento.cursiva
        elif isinstance(elemento, Tabla):
            _tabla(doc, elemento)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(ruta))
    return ruta


def _tabla(doc, tabla: Tabla) -> None:
    columnas = max(len(f) for f in tabla.filas)
    t = doc.add_table(rows=0, cols=columnas)
    t.style = "Table Grid"
    anchos = tabla.anchos or ([0.32, 0.68] if tabla.clave_valor else [1 / columnas] * columnas)
    for i, fila in enumerate(tabla.filas):
        celdas = t.add_row().cells
        for j in range(columnas):
            texto = fila[j] if j < len(fila) else ""
            es_encabezado = (tabla.encabezado and i == 0) or (tabla.clave_valor and j == 0)
            _escribir_celda(celdas[j], texto, negrita=es_encabezado)
            celdas[j].width = Cm(ANCHO_UTIL_CM * anchos[j])
            if es_encabezado:
                _sombrear(celdas[j], FONDO_ENCABEZADO)
    doc.add_paragraph()
