"""Representación léxica dispersa tipo BM25 (señal léxica de la búsqueda híbrida, D-6).

El componente de frecuencia de BM25 se calcula aquí; el IDF lo aplica Qdrant sobre la
colección (`Modifier.IDF`). Así los identificadores exactos, como `PE-MI-05` o `ITI-501`,
se recuperan aunque el modelo denso los diluya.
"""

import re
import unicodedata
import zlib
from collections import Counter

STOPWORDS = frozenset([
    "a", "al", "algo", "algunas", "algunos", "ante", "antes", "como", "con", "contra", "cual",
    "cuando", "de", "del", "desde", "donde", "durante", "e", "el", "ella", "ellas", "ellos", "en",
    "entre", "era", "es", "esa", "esas", "ese", "eso", "esos", "esta", "estas", "este", "esto",
    "estos", "fue", "fueron", "ha", "han", "hasta", "hay", "la", "las", "le", "les", "lo", "los",
    "mas", "me", "mi", "mientras", "muy", "no", "nos", "o", "os", "otra", "otras", "otro", "otros",
    "para", "pero", "poco", "por", "porque", "que", "quien", "se", "sea", "segun", "ser", "si",
    "sin", "sino", "sobre", "son", "su", "sus", "tambien", "tanto", "te", "tiene", "tienen",
    "todo", "todos", "tu", "tus", "un", "una", "uno", "unos", "y", "ya", "cada", "debe", "deben",
    "puede", "pueden",
])

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c))


def _raiz(token: str) -> str:
    # Plural simple: «resultados» y «resultado» comparten término. No se toca a los códigos.
    if "-" in token or token.isdigit() or len(token) <= 4:
        return token
    if token.endswith("es") and len(token) > 6:
        return token[:-2]
    if token.endswith("s"):
        return token[:-1]
    return token


def tokenizar(texto: str) -> list[str]:
    tokens = []
    for token in _TOKEN.findall(normalizar(texto)):
        if token in STOPWORDS or len(token) < 2:
            continue
        tokens.append(_raiz(token))
        if "-" in token:  # «pe-mi-05» también aporta «pe», «mi», «05»
            tokens.extend(p for p in token.split("-") if len(p) >= 2 and p not in STOPWORDS)
    return tokens


def indice_termino(termino: str) -> int:
    return zlib.crc32(termino.encode("utf-8")) & 0x7FFFFFFF


def vector_documento(
    texto: str, k1: float = 1.2, b: float = 0.75, longitud_media: float = 160
) -> tuple[list[int], list[float]]:
    tokens = tokenizar(texto)
    conteo = Counter(tokens)
    largo = len(tokens) or 1
    pesos: dict[int, float] = {}
    for termino, tf in conteo.items():
        valor = tf * (k1 + 1) / (tf + k1 * (1 - b + b * largo / longitud_media))
        indice = indice_termino(termino)
        pesos[indice] = pesos.get(indice, 0.0) + valor
    indices = sorted(pesos)
    return indices, [pesos[i] for i in indices]


def vector_consulta(texto: str) -> tuple[list[int], list[float]]:
    indices = sorted({indice_termino(t) for t in tokenizar(texto)})
    return indices, [1.0] * len(indices)
