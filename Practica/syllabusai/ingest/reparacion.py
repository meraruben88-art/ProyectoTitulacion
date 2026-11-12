"""Reparación del texto de las mallas del CES.

Los PDF que genera la plataforma del CES justifican el texto en columnas muy estrechas. Al
extraerlo aparecen dos defectos que se repiten en todas las mallas:

- letras sueltas: «R e s u e l v e problemas», «COMPUTAC I O N»;
- palabras pegadas o partidas: «Nombredela asignatura», «Electromag netismo».

Se corrigen con un vocabulario construido a partir de los documentos institucionales con texto
limpio (`vocabulario_es.txt`) más los términos técnicos del propio documento. La corrección es
conservadora: solo une o separa cuando el resultado son palabras conocidas. Lo que no se puede
resolver queda como estaba y lo revisa el administrador antes de publicar la malla.
"""

import math
import re
from collections import Counter
from functools import cache
from pathlib import Path

from syllabusai.retrieval.lexico import normalizar

RUTA_VOCABULARIO = Path(__file__).with_name("vocabulario_es.txt")
_L = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
_LETRAS = re.compile(f"^[{_L}]+$")
_PARTES = re.compile(f"^([^{_L}]*)([{_L}]+)([^{_L}]*)$")
_UNA_LETRA = {"a", "y", "o", "e", "u"}
# Palabras cortas que pueden quedar separadas al segmentar («Nombredela» -> «Nombre de la»).
_FUNCIONALES = {"de", "la", "el", "en", "los", "las", "del", "al", "un", "una", "y", "a", "o",
                "e", "u", "con", "por", "para", "sus", "su", "que", "se", "lo", "ti", "ia", "es"}
# Terminaciones que no se separan nunca: «propiedad es», «medicion es».
# Terminaciones de palabras que no se separan aunque no estén en el vocabulario.
_TERMINACIONES = ("cion", "sion", "mente", "idad", "ismo", "ista", "ble", "ivo", "iva", "ivos",
                  "ivas", "ado", "ada", "ados", "adas", "ico", "ica", "icos", "icas", "ciones")
# Letras con que puede terminar una palabra en español.
_FINALES = set("aeiouslnrdzyx")
_SUFIJOS = {"es", "os", "as", "s", "n", "an", "en", "ia", "ion", "on"}


class Vocabulario:
    def __init__(self, frecuencias: Counter):
        self.frecuencias = Counter()
        for palabra, n in frecuencias.items():
            self.frecuencias[normalizar(palabra)] += n
        self.total = sum(self.frecuencias.values()) or 1
        self.max_largo = max((len(p) for p in self.frecuencias), default=1)

    def conoce(self, palabra: str) -> bool:
        clave = normalizar(palabra)
        if len(clave) == 1:
            return clave in _UNA_LETRA
        return clave in self.frecuencias

    def _costo(self, palabra: str) -> float:
        if len(palabra) == 1 and palabra not in _UNA_LETRA:
            return math.inf
        n = self.frecuencias.get(palabra)
        return math.inf if n is None else math.log(self.total / n) + 2.0

    def segmentar(self, texto: str) -> list[str] | None:
        """Divide una cadena sin espacios en palabras conocidas aceptables; None si no se puede."""
        texto = normalizar(texto)
        n = len(texto)
        mejor = [0.0] + [math.inf] * n
        corte = [0] * (n + 1)
        for j in range(1, n + 1):
            for i in range(max(0, j - self.max_largo), j):
                if mejor[i] < math.inf:
                    c = mejor[i] + self._costo(texto[i:j])
                    if c < mejor[j]:
                        mejor[j], corte[j] = c, i
        if mejor[n] == math.inf:
            return None
        partes, j = [], n
        while j > 0:
            partes.append(texto[corte[j]:j])
            j = corte[j]
        partes.reverse()
        if len(partes) > 1:
            if partes[-1] in _SUFIJOS:
                return None
            # Las piezas cortas solo valen si son palabras funcionales o muy frecuentes.
            if any(len(p) <= 3 and p not in _FUNCIONALES and self.frecuencias.get(p, 0) < 20
                   for p in partes):
                return None
        return partes

    def ampliar(self, palabras: list[str]) -> "Vocabulario":
        """Añade los términos técnicos del documento, sin las palabras pegadas."""
        nuevas = Counter()
        for i, palabra in enumerate(palabras):
            # Los nombres en mayúsculas de la malla vienen partidos («FUNDAMEN TOS»): no se aprenden.
            if len(palabra) < 5 or not _LETRAS.match(palabra) or palabra.isupper() or self.conoce(palabra):
                continue
            # Un fragmento cortado («electrostátic», «Introducció n») no es un término.
            siguiente = palabras[i + 1] if i + 1 < len(palabras) else ""
            if normalizar(palabra[-1]) not in _FINALES or normalizar(palabra).endswith(("ci", "si")):
                continue
            if len(siguiente) <= 2 and siguiente.isalpha() and normalizar(siguiente) not in _FUNCIONALES:
                continue
            partes = self.segmentar(palabra)
            if partes is None or len(partes) == 1:
                nuevas[palabra] += 1
        return Vocabulario(self.frecuencias + nuevas)


# Restos de palabras cortadas por el salto de línea en los documentos de origen.
_FRAGMENTOS = {"cion", "ciones", "sion", "siones", "tos", "miento", "mientos", "mente", "ores",
               "dad", "dades", "ica", "icas", "ico", "icos"}


def _sin_fragmentos(frecuencias: Counter) -> Counter:
    """Quita del vocabulario los principios de palabra cortados («fundamen» de «fundamentos»):
    son poco frecuentes y hay una palabra conocida, más frecuente, que los continúa."""
    claves = sorted(frecuencias)
    limpias = Counter()
    for i, palabra in enumerate(claves):
        n = frecuencias[palabra]
        if palabra in _FRAGMENTOS:
            continue
        if n <= 5 and len(palabra) >= 4:
            continua = False
            for otra in claves[i + 1:i + 40]:
                if not otra.startswith(palabra):
                    break
                if 2 <= len(otra) - len(palabra) <= 6 and frecuencias[otra] >= n:
                    continua = True
                    break
            if continua:
                continue
        limpias[palabra] = n
    return limpias


@cache
def vocabulario_base() -> Vocabulario:
    frecuencias = Counter()
    for linea in RUTA_VOCABULARIO.read_text(encoding="utf-8").splitlines():
        if linea and not linea.startswith("#"):
            palabra, _, n = linea.partition("\t")
            frecuencias[normalizar(palabra)] += int(n or 1)
    return Vocabulario(_sin_fragmentos(frecuencias))


def _recortar(original: str, segmentos: list[str]) -> list[str]:
    """Corta la cadena original (con mayúsculas y tildes) en los largos de los segmentos."""
    partes, i = [], 0
    for s in segmentos:
        partes.append(original[i:i + len(s)])
        i += len(s)
    return partes


def _envolver(partes: list[str], antes: str, despues: str) -> list[str]:
    partes = list(partes)
    partes[0] = antes + partes[0]
    partes[-1] = partes[-1] + despues
    return partes


def _letra_suelta(token: str) -> bool:
    return len(token) == 1 and token.isalpha()


def _segmentar_con_cola(texto: str, voc: Vocabulario) -> list[str] | None:
    """Como `segmentar`, pero admite una cola desconocida de 3 o más letras («y dos planos»)."""
    segmentos = voc.segmentar(texto)
    if segmentos is not None:
        return _recortar(texto, segmentos)
    for k in range(len(texto) - 3, 0, -1):
        cabeza = voc.segmentar(texto[:k])
        if cabeza is not None:
            return [*_recortar(texto[:k], cabeza), texto[k:]]
    return None


def _unir_corrida(previo: str | None, corrida: str, voc: Vocabulario) -> tuple[bool, list[str]]:
    """Une una corrida de letras sueltas, absorbiendo si hace falta el final de la palabra
    anterior cortada. Devuelve si absorbió la anterior y las palabras resultantes."""
    # Solo se continúa la palabra anterior si la caja coincide: «COMPUTAC» + «ION», no «Newton» + «T».
    misma_caja = previo is not None and (
        corrida[0].islower() or (previo.isupper() and corrida.isupper()))
    # «PROGRAMA» + «CION» (+ «BASICA»): la anterior es palabra, pero unida a la corrida también.
    if misma_caja and voc.conoce(previo):
        for k in range(len(corrida), 1, -1):
            if voc.conoce(previo + corrida[:k]):
                resto = corrida[k:]
                segmentos = voc.segmentar(resto) if resto else []
                if segmentos is not None:
                    return True, [previo + corrida[:k], *_recortar(resto, segmentos)]
    if misma_caja and not voc.conoce(previo):
        for k in range(len(corrida), 0, -1):
            if voc.conoce(previo + corrida[:k]):
                resto = corrida[k:]
                if not resto:
                    return True, [previo + corrida]
                segmentos = voc.segmentar(resto)
                if segmentos is not None:
                    return True, [previo + corrida[:k], *_recortar(resto, segmentos)]
        # La palabra cortada puede no estar en el vocabulario: «consideraci» + «ón» + «sus».
        # Solo se acepta si queda una palabra con forma de palabra («-ción», «-ica»…) o si la
        # anterior termina en una letra con que no termina ninguna palabra («Electromag»).
        def plausible(palabra: str) -> bool:
            return (normalizar(previo[-1]) not in _FINALES
                    or normalizar(palabra).endswith(_TERMINACIONES + ("on",)))

        for k in range(1, len(corrida)):
            segmentos = voc.segmentar(corrida[k:])
            if segmentos is not None and len(segmentos[0]) >= 2 and plausible(previo + corrida[:k]):
                return True, [previo + corrida[:k], *_recortar(corrida[k:], segmentos)]
        # Una «y» final es la conjunción: «electrostátic a y» -> «electrostática y».
        if len(corrida) >= 2 and corrida[-1] in "yY" and plausible(previo + corrida[:-1]):
            return True, [previo + corrida[:-1], corrida[-1]]
        if plausible(previo + corrida):
            return True, [previo + corrida]
    if voc.conoce(corrida):
        return False, [corrida]
    return False, (_segmentar_con_cola(corrida, voc) or [corrida])


def reparar(texto: str, vocabulario: Vocabulario | None = None) -> str:
    """Devuelve el texto con las letras sueltas unidas y las palabras pegadas separadas."""
    voc = vocabulario or vocabulario_base()
    tokens = texto.split()

    # 1. Corridas de letras sueltas: «d e l a» -> «de la»; «COMPUTAC I O N» -> «COMPUTACION».
    paso1: list[str] = []
    i = 0
    while i < len(tokens):
        j = i
        while j < len(tokens) and _letra_suelta(tokens[j]):
            j += 1
        if j - i < 2:
            paso1.append(tokens[i])
            i += 1
            continue
        corrida = "".join(tokens[i:j])
        previo = _PARTES.match(paso1[-1]) if paso1 else None
        absorbe, palabras = _unir_corrida(
            previo.group(2) if previo and not previo.group(3) else None, corrida, voc)
        if absorbe:
            paso1.pop()
            palabras = _envolver(palabras, previo.group(1), "")
        paso1.extend(palabras)
        i = j

    # 2. Palabras partidas: «Electromag netismo», «FUNDAMEN TOSDELAS» -> «FUNDAMENTOS DE LAS».
    paso2: list[str] = []
    for token in paso1:
        previo = _PARTES.match(paso2[-1]) if paso2 else None
        actual = _PARTES.match(token)
        if previo and actual and not previo.group(3) and not actual.group(1):
            a, b = previo.group(2), actual.group(2)
            # Letra final suelta que no es palabra: «PROYECTO S», «fundamento s».
            if len(b) == 1 and not voc.conoce(b) and len(a) >= 3:
                paso2[-1] = previo.group(1) + a + b + actual.group(3)
                continue
            if not voc.conoce(a) or (not voc.conoce(b) and len(b) > 1):
                segmentos = voc.segmentar(a + b)
                if segmentos and len(segmentos[0]) > len(a):
                    paso2[-1:] = _envolver(_recortar(a + b, segmentos), previo.group(1), actual.group(3))
                    continue
            # Dos fragmentos desconocidos seguidos, el primero sin terminación posible en español,
            # son una palabra partida: «Electromag netismo», «Electrostáti ca».
            if (len(a) >= 4 and not voc.conoce(a)
                    and (not voc.conoce(b) or (len(b) <= 2 and b.lower() not in _FUNCIONALES))
                    and (normalizar(a[-1]) not in _FINALES or len(b) <= 2)
                    and (b.islower() or (a.isupper() and b.isupper()))):
                paso2[-1] = previo.group(1) + a + b + actual.group(3)
                continue
        paso2.append(token)

    # 3. Palabras pegadas: «Nombredela» -> «Nombre de la».
    salida: list[str] = []
    for token in paso2:
        partes = _PARTES.match(token)
        if (partes and len(partes.group(2)) >= 6 and not voc.conoce(partes.group(2))
                and not normalizar(partes.group(2)).endswith(_TERMINACIONES)):
            segmentos = voc.segmentar(partes.group(2))
            if segmentos and len(segmentos) > 1:
                salida.extend(_envolver(_recortar(partes.group(2), segmentos),
                                        partes.group(1), partes.group(3)))
                continue
            # Muy largas casi siempre están pegadas: se admite una cola desconocida.
            if len(partes.group(2)) >= 12:
                con_cola = _segmentar_con_cola(partes.group(2), voc)
                if con_cola and len(con_cola) > 1 and len(con_cola[-1]) >= 5:
                    salida.extend(_envolver(con_cola, partes.group(1), partes.group(3)))
                    continue
        salida.append(token)
    texto = " ".join(salida)
    return re.sub(r"\s+([,.;:)])", r"\1", texto).replace("( ", "(")
