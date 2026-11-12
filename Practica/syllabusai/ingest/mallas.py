"""Extracción de las asignaturas de las mallas curriculares del CES (carpeta MALLAS).

Las mallas aprobadas por el CES traen, por asignatura, el nivel, la unidad de organización, los
resultados de aprendizaje, los contenidos mínimos y las horas por componente. Esos son justo los
datos que el sílabo importa sin modificar (ficha curricular). Cada PDF tiene su maquetación, por
eso hay un perfil por malla: páginas de la tabla, columnas y orden de las horas.

La tabla se reconstruye por coordenadas: los límites de las columnas se toman de una página en
que PyMuPDF detecta la rejilla y se aplican a todas, porque en varias páginas el detector de
tablas no la encuentra. Las filas se separan por el marcador de la primera columna («No es de
itinerario» o el número de la asignatura); lo que aparece antes del primer marcador de una
página continúa la asignatura de la página anterior.

El texto se repara (`reparacion.py`) y se marca como extraído automáticamente: el administrador
lo revisa y lo publica antes de que los docentes lo usen como dato oficial.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import pymupdf

from syllabusai.ingest.reparacion import Vocabulario, reparar, vocabulario_base


@dataclass(frozen=True)
class Perfil:
    sigla: str
    carrera: str
    patron: str  # parte del nombre del archivo
    paginas: tuple[int, int] | None  # rango 1-based inclusivo de la tabla de asignaturas
    pagina_columnas: int  # página en que se detecta la rejilla de referencia
    columnas: int
    nombre: int
    nivel: int
    unidad: int
    ra: int
    contenidos: int
    horas: dict[str, int]  # contacto, practicas, autonomas, total -> índice de columna
    marcador: str  # expresión de la primera columna que abre una asignatura
    ra_numerados: bool = False  # «RAP 1 …» en lugar de enunciados seguidos


PERFILES = (
    Perfil(
        sigla="ITI", carrera="Ingeniería en Tecnologías de la Información",
        patron="TecnologiasDeLaInformacion", paginas=(7, 37), pagina_columnas=7, columnas=12,
        nombre=1, nivel=2, unidad=3, ra=4, contenidos=5,
        horas={"contacto": 6, "autonomas": 7, "practicas": 8, "total": 11},
        marcador=r"^No es de", ra_numerados=False,
    ),
    Perfil(
        sigla="IND", carrera="Ingeniería Industrial",
        patron="IngenieriaIndustrial", paginas=(36, 74), pagina_columnas=37, columnas=10,
        nombre=1, nivel=2, unidad=3, ra=4, contenidos=5,
        horas={"contacto": 6, "practicas": 7, "autonomas": 8, "total": 9},
        marcador=r"^\d{1,2}$", ra_numerados=True,
    ),
    Perfil(
        sigla="ELE", carrera="Ingeniería Eléctrica", patron="Eléctrica", paginas=None,
        pagina_columnas=0, columnas=0, nombre=0, nivel=0, unidad=0, ra=0, contenidos=0, horas={},
        marcador="",
    ),
)


@dataclass
class AsignaturaExtraida:
    nombre: str
    nivel: int
    unidad: str
    resultados: list[str]
    contenidos: list[str]
    horas_contacto: int
    horas_practicas: int
    horas_autonomas: int
    total: int
    pagina: int
    avisos: list[str] = field(default_factory=list)


@dataclass
class MallaExtraida:
    perfil: Perfil
    archivo: Path
    paginas: int
    asignaturas: list[AsignaturaExtraida]
    avisos: list[str] = field(default_factory=list)


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def perfil_de(archivo: Path) -> Perfil | None:
    nombre = _sin_tildes(Path(archivo).name)
    for perfil in PERFILES:
        if _sin_tildes(perfil.patron) in nombre:
            return perfil
    return None


def _lineas(pagina) -> list[list[dict]]:
    """Caracteres de la página agrupados por línea, tal como están codificados (los espacios
    son los del PDF: no se infieren por la posición)."""
    datos = pagina.get_text("rawdict", flags=0)
    return [[c for s in linea["spans"] for c in s["chars"]]
            for bloque in datos["blocks"] for linea in bloque.get("lines", [])]


def _texto(lineas: list[list[dict]], rect) -> str:
    """Texto de una celda: los caracteres cuyo centro cae dentro del rectángulo."""
    partes = []
    for linea in lineas:
        dentro = "".join(
            c["c"] for c in linea
            if rect.x0 <= (c["bbox"][0] + c["bbox"][2]) / 2 <= rect.x1
            and rect.y0 <= (c["bbox"][1] + c["bbox"][3]) / 2 <= rect.y1
        )
        if dentro.strip():
            partes.append(dentro)
    return " ".join(partes)


def _limites_columnas(documento, perfil: Perfil) -> list[tuple[float, float]]:
    pagina = documento[perfil.pagina_columnas - 1]
    for tabla in pagina.find_tables().tables:
        celdas = tabla.rows[0].cells
        if len(celdas) == perfil.columnas and all(celdas):
            return [(c[0], c[2]) for c in celdas]
    raise ValueError(f"No se encontró la rejilla de la malla en la página {perfil.pagina_columnas}")


def _cortes_horizontales(pagina, perfil: Perfil) -> list[float]:
    """Posiciones verticales que separan filas: líneas de la rejilla o filas detectadas."""
    ys = sorted({
        round(it[1].y, 1) for dibujo in pagina.get_drawings() for it in dibujo["items"]
        if it[0] == "l" and abs(it[1].y - it[2].y) < 0.5 and abs(it[1].x - it[2].x) > 20
    })
    if len(ys) < 2:
        for tabla in pagina.find_tables().tables:
            if len(tabla.rows[0].cells) >= perfil.columnas:
                ys = sorted({round(f.bbox[1], 1) for f in tabla.rows} | {round(tabla.bbox[3], 1)})
                break
    if len(ys) < 2:
        ys = [36.0, pagina.rect.height - 36]
    unicos: list[float] = []
    for y in ys:
        if not unicos or y - unicos[-1] > 2:
            unicos.append(y)
    return unicos


def _filas_crudas(documento, perfil: Perfil) -> list[tuple[int, list[str]]]:
    columnas = _limites_columnas(documento, perfil)
    marcador = re.compile(perfil.marcador)
    primera, ultima = perfil.paginas
    filas: list[tuple[int, list[str]]] = []
    x0, x1 = columnas[0]
    for numero in range(primera, ultima + 1):
        pagina = documento[numero - 1]
        lineas = _lineas(pagina)
        cortes = _cortes_horizontales(pagina, perfil)
        # Dentro de un tramo puede haber más de una asignatura si faltan líneas: se corta
        # también donde la primera columna abre una asignatura nueva.
        aperturas = [
            b[1] - 1 for b in pagina.get_text("blocks")
            if x0 <= (b[0] + b[2]) / 2 <= x1 and marcador.match(" ".join(b[4].split()))
            and cortes[0] <= b[1] <= cortes[-1]
        ]
        ys = sorted(set(cortes) | {y for y in aperturas if all(abs(y - c) > 4 for c in cortes)})
        for y0, y1 in pairwise(ys):
            celdas = [_texto(lineas, pymupdf.Rect(cx0, y0, cx1, y1)) for cx0, cx1 in columnas]
            if not any(c.strip() for c in celdas) or celdas[perfil.nombre].startswith("Nombre"):
                continue  # vacío o encabezado de la tabla
            if marcador.match(" ".join(celdas[0].split())):
                filas.append((numero, celdas))
            elif filas:  # continúa la asignatura de la página anterior
                anterior = filas[-1][1]
                filas[-1] = (filas[-1][0], [f"{a} {b}".strip() for a, b in zip(anterior, celdas, strict=True)])
    return filas


def _entero(texto: str) -> int:
    digitos = re.findall(r"\d+", texto.replace(",", "").replace(".", ""))
    return int(digitos[0]) if digitos else 0


_VERBO = re.compile(r"^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}$")
_FUNCIONALES = {"de", "la", "el", "en", "los", "las", "del", "al", "un", "una", "y", "o", "a",
                "con", "por", "para", "e", "u", "su", "sus"}


def _partir_por_mayusculas(texto: str, verbos: bool) -> list[str]:
    """Separa enunciados seguidos sin numeración: un nuevo enunciado empieza con una palabra
    capitalizada (un verbo en los RA) que sigue a una palabra no funcional y sin coma."""
    tokens = texto.split()
    partes, actual = [], []
    for i, token in enumerate(tokens):
        siguiente = tokens[i + 1] if i + 1 < len(tokens) else ""
        if actual and _VERBO.match(token):
            previo = actual[-1]
            nuevo = previo.lower() not in _FUNCIONALES and not previo.endswith(",")
            if verbos:
                # Un RA empieza con un verbo en tercera persona («Resuelve», «Opera») seguido
                # de minúscula: así no se corta en «Base de Datos» ni en «Newton».
                nuevo = nuevo and _sin_tildes(token.lower())[-1] in "ae" and siguiente[:1].islower()
            if nuevo:
                partes.append(" ".join(actual))
                actual = []
        actual.append(token)
    if actual:
        partes.append(" ".join(actual))
    return [p.strip(" .;") for p in partes if p.strip(" .;")]


def _limpiar_ruido(texto: str) -> str:
    texto = re.sub(r"\s\.-\s?", " ", texto)          # «.-» de las viñetas del CES
    texto = re.sub(r"(\s\.){2,}", ".", texto)        # «. . .»
    texto = re.sub(r"\s+([,.;:])", r"\1", texto)
    return " ".join(texto.split())


def _resultados(texto: str, numerados: bool, voc: Vocabulario) -> list[str]:
    texto = _limpiar_ruido(reparar(texto, voc))
    if numerados:
        partes = re.split(r"\bRAP\s*\d+\s*[.:-]*\s*", texto)
    else:
        partes = _partir_por_mayusculas(texto, verbos=True)
    return [_limpiar_ruido(p).strip(" .;-") + "." for p in partes if len(p.strip(" .;-")) > 8]


def _contenidos(texto: str, numerados: bool, voc: Vocabulario) -> list[str]:
    texto = _limpiar_ruido(reparar(texto, voc))
    if numerados:
        talleres = re.split(r"\bTaller\s*(\d+)\s*", texto)
        if len(talleres) > 1:
            items = []
            for n, cuerpo in zip(talleres[1::2], talleres[2::2], strict=False):
                cuerpo = re.sub(r"\b\d{1,3}\s+", "", cuerpo)  # numeración «11», «12» de los temas
                temas = [t.strip(" .,;") for t in re.split(r"\.\s+", cuerpo) if len(t.strip(" .,;")) > 2]
                if temas:
                    items.append(f"Taller {n}: {temas[0]}" + (f" ({'; '.join(temas[1:])})" if temas[1:] else ""))
            return items
        return [t.strip(" .,;") for t in re.split(r"\.\s+", texto) if len(t.strip(" .,;")) > 2]
    if texto.isupper() or sum(c.isupper() for c in texto) > 0.6 * sum(c.isalpha() for c in texto):
        return [texto.strip(" .;")]
    return _partir_por_mayusculas(texto, verbos=False)


def _nombre(texto: str, voc: Vocabulario) -> str:
    nombre = " ".join(reparar(texto, voc).split())
    if nombre.isupper():
        menores = {"de", "la", "el", "en", "y", "a", "los", "las", "del", "e", "para"}
        palabras = [p.lower() if p.lower() in menores else p.capitalize() for p in nombre.split()]
        palabras[0] = palabras[0].capitalize()
        nombre = " ".join(p if p not in ("Ti", "Tic", "Tics") else p.upper() for p in palabras)
    return nombre


def extraer_malla(archivo: Path, perfil: Perfil | None = None) -> MallaExtraida:
    archivo = Path(archivo)
    perfil = perfil or perfil_de(archivo)
    if perfil is None:
        raise ValueError(f"No hay un perfil de extracción para {archivo.name}")
    documento = pymupdf.open(archivo)
    if perfil.paginas is None:
        aviso = ("Este documento del CES no trae la tabla de asignaturas con RA y contenidos "
                 "mínimos: se indexa como evidencia y las asignaturas se registran a mano.")
        return MallaExtraida(perfil, archivo, len(documento), [], [aviso])
    filas = _filas_crudas(documento, perfil)
    # Vocabulario ampliado con los términos técnicos que aparecen bien escritos en la malla.
    palabras = " ".join(documento[i].get_text() for i in range(len(documento))).split()
    voc = vocabulario_base().ampliar(palabras)
    asignaturas = []
    for pagina, celdas in filas:
        nivel = _entero(celdas[perfil.nivel])
        horas = {k: _entero(celdas[i]) for k, i in perfil.horas.items()}
        nombre = _nombre(celdas[perfil.nombre], voc)
        if not nombre or not nivel:
            continue
        a = AsignaturaExtraida(
            nombre=nombre, nivel=nivel, unidad=_nombre(celdas[perfil.unidad], voc),
            resultados=_resultados(celdas[perfil.ra], perfil.ra_numerados, voc),
            contenidos=_contenidos(celdas[perfil.contenidos], perfil.ra_numerados, voc),
            horas_contacto=horas["contacto"], horas_practicas=horas["practicas"],
            horas_autonomas=horas["autonomas"], total=horas["total"], pagina=pagina,
        )
        suma = a.horas_contacto + a.horas_practicas + a.horas_autonomas
        if suma != a.total:
            a.avisos.append(f"Las horas por componente suman {suma} y el total declarado es {a.total}.")
        if len(a.resultados) > 4:
            a.avisos.append(f"Se reconocieron {len(a.resultados)} resultados de aprendizaje; el "
                            "formato admite cuatro: los restantes se unieron al RA4.")
            a.resultados = a.resultados[:3] + [" ".join(a.resultados[3:])]
        if not a.resultados:
            a.avisos.append("No se reconocieron los resultados de aprendizaje.")
        if not a.contenidos:
            a.avisos.append("No se reconocieron los contenidos mínimos.")
        asignaturas.append(a)
    return MallaExtraida(perfil, archivo, len(documento), asignaturas)
