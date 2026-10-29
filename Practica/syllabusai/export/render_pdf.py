"""Renderizador PDF del documento lógico (reportlab).

Se usa cuando no hay LibreOffice para convertir el DOCX (D-7). Dibuja los mismos elementos y
tablas que el DOCX, por lo que ambos archivos tienen el mismo contenido y orden.
"""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from syllabusai.export.documento import Elemento, Parrafo, Tabla, Titulo

MORADO = colors.HexColor("#3B1E6E")
FONDO = colors.HexColor("#E8E2F2")
ANCHO_UTIL = A4[0] - 4 * cm


def _estilos():
    base = getSampleStyleSheet()
    return {
        "portada": ParagraphStyle("portada", parent=base["Title"], fontSize=13, textColor=MORADO,
                                  alignment=TA_CENTER, spaceAfter=4),
        1: ParagraphStyle("t1", parent=base["Heading2"], fontSize=12, textColor=MORADO, spaceBefore=10),
        2: ParagraphStyle("t2", parent=base["Heading3"], fontSize=10.5, textColor=MORADO, spaceBefore=6),
        "parrafo": ParagraphStyle("p", parent=base["BodyText"], fontSize=9.5, leading=12),
        "cursiva": ParagraphStyle("pc", parent=base["BodyText"], fontSize=9, leading=11,
                                  fontName="Helvetica-Oblique"),
        "celda": ParagraphStyle("c", parent=base["BodyText"], fontSize=8, leading=10),
        "celda_n": ParagraphStyle("cn", parent=base["BodyText"], fontSize=8, leading=10,
                                  fontName="Helvetica-Bold"),
    }


def _texto(valor: str) -> str:
    return escape(valor).replace("\n", "<br/>")


def renderizar(elementos: list[Elemento], ruta: Path) -> Path:
    estilos = _estilos()
    historia = []
    for elemento in elementos:
        if isinstance(elemento, Titulo):
            estilo = estilos["portada"] if elemento.nivel == 0 else estilos[min(elemento.nivel, 2)]
            historia.append(Paragraph(_texto(elemento.texto), estilo))
        elif isinstance(elemento, Parrafo):
            estilo = estilos["cursiva"] if elemento.cursiva else estilos["parrafo"]
            historia.append(Paragraph(_texto(elemento.texto), estilo))
        elif isinstance(elemento, Tabla):
            historia += [_tabla(elemento, estilos), Spacer(1, 6)]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    plantilla = SimpleDocTemplate(
        str(ruta), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm,
        bottomMargin=2 * cm, title="Sílabo de Proyecto Formativo", author="SyllabusAI",
    )
    plantilla.build(historia, onFirstPage=_pie, onLaterPages=_pie)
    return ruta


def _pie(lienzo, documento) -> None:
    lienzo.saveState()
    lienzo.setFont("Helvetica", 7.5)
    lienzo.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {documento.page}")
    lienzo.restoreState()


def _tabla(tabla: Tabla, estilos) -> Table:
    columnas = max(len(f) for f in tabla.filas)
    anchos = tabla.anchos or ([0.32, 0.68] if tabla.clave_valor else [1 / columnas] * columnas)
    datos, comandos = [], [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, fila in enumerate(tabla.filas):
        celdas = []
        for j in range(columnas):
            texto = fila[j] if j < len(fila) else ""
            negrita = (tabla.encabezado and i == 0) or (tabla.clave_valor and j == 0)
            celdas.append(Paragraph(_texto(texto), estilos["celda_n" if negrita else "celda"]))
        datos.append(celdas)
    if tabla.encabezado:
        comandos.append(("BACKGROUND", (0, 0), (-1, 0), FONDO))
    if tabla.clave_valor:
        comandos.append(("BACKGROUND", (0, 0), (0, -1), FONDO))
    t = Table(datos, colWidths=[ANCHO_UTIL * a for a in anchos], repeatRows=1 if tabla.encabezado else 0)
    t.setStyle(TableStyle(comandos))
    return t
