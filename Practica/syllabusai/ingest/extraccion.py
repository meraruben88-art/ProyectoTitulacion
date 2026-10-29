"""Extracción de texto con jerarquía, página y tablas (RF-03, RF-08).

Cada documento se convierte en una secuencia de bloques en orden de lectura. Un bloque es un
título (con su nivel), un párrafo o una tabla. Las tablas se extraen fila a fila para que la
malla curricular y los contenidos mínimos no se pierdan como texto plano desordenado.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document as DocumentoDocx
from docx.table import Table
from docx.text.paragraph import Paragraph


@dataclass
class Bloque:
    texto: str
    pagina: int
    nivel_titulo: int | None = None  # 1, 2 o 3 si el bloque es un título
    filas: list[list[str]] = field(default_factory=list)  # solo en tablas

    @property
    def es_tabla(self) -> bool:
        return bool(self.filas)


class ErrorExtraccion(ValueError):
    """El archivo no se pudo leer como PDF o DOCX."""


def extraer(ruta: Path) -> list[Bloque]:
    ruta = Path(ruta)
    sufijo = ruta.suffix.lower()
    if sufijo == ".pdf":
        bloques = _extraer_pdf(ruta)
    elif sufijo == ".docx":
        bloques = _extraer_docx(ruta)
    else:
        raise ErrorExtraccion(f"Formato no admitido: {sufijo}")
    return [b for b in bloques if b.texto.strip()]


def texto_tabla(filas: list[list[str]]) -> str:
    return "\n".join(" | ".join(celda for celda in fila) for fila in filas)


def _normalizar_espacios(texto: str) -> str:
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)  # palabras partidas al final de línea
    return " ".join(texto.split())


# --- PDF ---------------------------------------------------------------------------------

_SOLO_NUMERO = re.compile(r"^\s*(p[áa]g(ina)?\.?\s*)?\d{1,4}(\s*(de|/)\s*\d{1,4})?\s*$", re.IGNORECASE)


def _extraer_pdf(ruta: Path) -> list[Bloque]:
    import pymupdf

    try:
        doc = pymupdf.open(ruta)
    except Exception as error:  # pymupdf lanza varios tipos según el daño del archivo
        raise ErrorExtraccion(f"No se pudo abrir el PDF: {error}") from error

    paginas = []  # por página: lista de (texto, tamaño, negrita, y) y tablas
    with doc:
        for numero, pagina in enumerate(doc, start=1):
            tablas, zonas = _tablas_pdf(pagina)
            alto = pagina.rect.height
            lineas = []
            for bloque in pagina.get_text("dict")["blocks"]:
                if bloque.get("type") != 0 or _dentro(bloque["bbox"], zonas):
                    continue
                texto, tamano, negrita = _texto_bloque(bloque)
                if not texto or sum(c.isalpha() for c in texto) < 2:
                    continue  # números de página y adornos sin letras
                _, y0, _, y1 = bloque["bbox"]
                if (y1 < alto * 0.06 or y0 > alto * 0.92) and len(texto.split()) <= 12:
                    continue  # encabezados y pies dentro de los márgenes
                lineas.append((texto, tamano, negrita, y0))
            paginas.append((numero, lineas, tablas))

    repetidos = _lineas_repetidas([[ln[0] for ln in lineas] for _, lineas, _ in paginas])
    tamanos = Counter()
    for _, lineas, _ in paginas:
        for texto, tamano, _, _ in lineas:
            if _clave_linea(texto) not in repetidos:
                tamanos[round(tamano)] += len(texto)
    cuerpo = tamanos.most_common(1)[0][0] if tamanos else 11
    titulos = sorted({round(t) for t in tamanos if t >= cuerpo * 1.15}, reverse=True)

    bloques = []
    for numero, lineas, tablas in paginas:
        elementos = [(ln[3], "texto", ln) for ln in lineas]
        elementos += [(y, "tabla", filas) for y, filas in tablas]
        for _, tipo, dato in sorted(elementos, key=lambda e: e[0]):
            if tipo == "tabla":
                bloques.append(Bloque(texto_tabla(dato), numero, filas=dato))
                continue
            texto, tamano, negrita, _ = dato
            if _clave_linea(texto) in repetidos or _SOLO_NUMERO.match(texto):
                continue
            nivel = None
            if round(tamano) in titulos and len(texto.split()) <= 20:
                nivel = min(titulos.index(round(tamano)) + 1, 3)
            elif negrita and len(texto.split()) <= 12 and not texto.endswith((".", ":", ";")):
                nivel = 3
            bloques.append(Bloque(texto, numero, nivel_titulo=nivel))
    return _sin_titulo_de_portada(bloques)


def _sin_titulo_de_portada(bloques: list[Bloque]) -> list[Bloque]:
    """Un único título de nivel 1 es el de la portada: no es una sección del documento."""
    if sum(1 for b in bloques if b.nivel_titulo == 1) != 1:
        return bloques
    for b in bloques:
        if b.nivel_titulo == 1:
            b.nivel_titulo = None
        elif b.nivel_titulo is not None:
            b.nivel_titulo = max(1, b.nivel_titulo - 1)
    return bloques


def _tablas_pdf(pagina) -> tuple[list[tuple[float, list[list[str]]]], list[tuple]]:
    try:
        encontradas = pagina.find_tables()
    except Exception:  # noqa: BLE001 — la detección de tablas es heurística; sin tablas se sigue
        return [], []
    tablas, zonas = [], []
    for tabla in encontradas.tables:
        # El texto de cada celda se lee por su recuadro: `extract()` pega palabras en algunos PDF.
        filas = [
            [_normalizar_espacios(pagina.get_textbox(celda)) if celda else "" for celda in fila.cells]
            for fila in tabla.rows
        ]
        filas = [f for f in filas if any(f)]
        # Una «tabla» de una sola columna suele ser maquetación, no datos.
        if len(filas) >= 2 and max(len(f) for f in filas) >= 2:
            tablas.append((tabla.bbox[1], filas))
            zonas.append(tabla.bbox)
    return tablas, zonas


def _dentro(caja, zonas) -> bool:
    x0, y0, x1, y1 = caja
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(z[0] <= cx <= z[2] and z[1] <= cy <= z[3] for z in zonas)


def _texto_bloque(bloque) -> tuple[str, float, bool]:
    partes, tamanos, negritas = [], Counter(), 0
    total = 0
    for linea in bloque["lines"]:
        texto_linea = "".join(s["text"] for s in linea["spans"])
        partes.append(texto_linea)
        for s in linea["spans"]:
            n = len(s["text"].strip())
            tamanos[s["size"]] += n
            total += n
            if s["flags"] & 16 or "bold" in s["font"].lower():
                negritas += n
    texto = _normalizar_espacios("\n".join(partes))
    tamano = tamanos.most_common(1)[0][0] if tamanos else 0
    return texto, tamano, total > 0 and negritas / total > 0.6


def _clave_linea(texto: str) -> str:
    return re.sub(r"\d+", "#", texto.casefold())


def _lineas_repetidas(paginas: list[list[str]]) -> set[str]:
    """Encabezados y pies: líneas cortas que se repiten en al menos la mitad de las páginas."""
    if len(paginas) < 3:
        return set()
    conteo = Counter()
    for lineas in paginas:
        conteo.update({_clave_linea(t) for t in lineas if len(t.split()) <= 12})
    umbral = max(3, len(paginas) // 2)
    return {clave for clave, n in conteo.items() if n >= umbral}


# --- DOCX --------------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extraer_docx(ruta: Path) -> list[Bloque]:
    try:
        doc = DocumentoDocx(str(ruta))
    except Exception as error:  # python-docx lanza KeyError, BadZipFile, etc.
        raise ErrorExtraccion(f"No se pudo abrir el DOCX: {error}") from error

    bloques, pagina = [], 1
    for elemento in doc.element.body.iterchildren():
        if elemento.tag == _W + "p":
            parrafo = Paragraph(elemento, doc)
            texto = _normalizar_espacios(parrafo.text)
            if texto:
                bloques.append(Bloque(texto, pagina, nivel_titulo=_nivel_estilo(parrafo)))
            pagina += _saltos_pagina(elemento)
        elif elemento.tag == _W + "tbl":
            tabla = Table(elemento, doc)
            filas = []
            for fila in tabla.rows:
                celdas = []
                for celda in fila.cells:
                    texto = _normalizar_espacios(celda.text)
                    if not celdas or texto != celdas[-1]:  # celdas combinadas se repiten
                        celdas.append(texto)
                if any(celdas):
                    filas.append(celdas)
            if filas:
                bloques.append(Bloque(texto_tabla(filas), pagina, filas=filas))
            pagina += _saltos_pagina(elemento)
    return bloques


def _saltos_pagina(elemento) -> int:
    renderizados = len(elemento.findall(f".//{_W}lastRenderedPageBreak"))
    manuales = sum(1 for br in elemento.iter(_W + "br") if br.get(_W + "type") == "page")
    return renderizados + manuales


def _nivel_estilo(parrafo: Paragraph) -> int | None:
    nombre = (parrafo.style.name if parrafo.style is not None else "").casefold()
    if nombre in ("title", "título", "titulo"):
        return 1
    coincidencia = re.match(r"(heading|t[íi]tulo)\s*(\d)", nombre)
    if coincidencia:
        return min(int(coincidencia.group(2)), 3)
    return None
