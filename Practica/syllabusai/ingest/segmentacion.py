"""Segmentación jerárquica en fragmentos (RF-04).

Un fragmento nunca mezcla dos secciones del documento: cada título cierra el fragmento en
curso. Dentro de una sección los párrafos se acumulan hasta `palabras_max`, con un solape de
párrafos finales para no cortar una idea por la mitad. Las tablas forman fragmentos propios y,
si se dividen, cada parte repite la fila de encabezado para no perder el significado de las
columnas.
"""

from dataclasses import dataclass

from syllabusai.ingest.extraccion import Bloque, texto_tabla


@dataclass
class FragmentoTexto:
    texto: str
    ruta_seccion: list[str]
    pagina_inicio: int
    pagina_fin: int


def _palabras(texto: str) -> int:
    return len(texto.split())


def segmentar(
    bloques: list[Bloque], palabras_max: int = 220, palabras_solape: int = 40
) -> list[FragmentoTexto]:
    fragmentos: list[FragmentoTexto] = []
    ruta: list[str] = []
    buffer: list[Bloque] = []

    def emitir(partes: list[Bloque]) -> None:
        if partes:
            fragmentos.append(FragmentoTexto(
                texto="\n".join(b.texto for b in partes),
                ruta_seccion=list(ruta),
                pagina_inicio=partes[0].pagina,
                pagina_fin=partes[-1].pagina,
            ))

    def cerrar() -> None:
        emitir(buffer)
        buffer.clear()

    for bloque in bloques:
        if bloque.nivel_titulo is not None:
            cerrar()
            ruta[:] = ruta[: bloque.nivel_titulo - 1] + [bloque.texto]
            continue
        if bloque.es_tabla:
            cerrar()
            for parte in _partir_tabla(bloque, palabras_max):
                emitir([parte])
            continue
        for pedazo in _partir_parrafo(bloque, palabras_max):
            if buffer and sum(_palabras(b.texto) for b in buffer) + _palabras(pedazo.texto) > palabras_max:
                emitir(buffer)
                buffer[:] = _solape(buffer, palabras_solape)
            buffer.append(pedazo)
    cerrar()
    return fragmentos


def _solape(buffer: list[Bloque], palabras_solape: int) -> list[Bloque]:
    """Últimos párrafos completos del fragmento anterior que caben en el solape."""
    conservados, total = [], 0
    for bloque in reversed(buffer):
        total += _palabras(bloque.texto)
        if total > palabras_solape:
            break
        conservados.insert(0, bloque)
    return conservados


def _partir_parrafo(bloque: Bloque, palabras_max: int) -> list[Bloque]:
    palabras = bloque.texto.split()
    if len(palabras) <= palabras_max:
        return [bloque]
    return [
        Bloque(" ".join(palabras[i:i + palabras_max]), bloque.pagina)
        for i in range(0, len(palabras), palabras_max)
    ]


def _partir_tabla(bloque: Bloque, palabras_max: int) -> list[Bloque]:
    encabezado, *filas = bloque.filas
    if not filas or _palabras(bloque.texto) <= palabras_max:
        return [bloque]
    partes, actual = [], [encabezado]
    for fila in filas:
        candidato = actual + [fila]
        if len(actual) > 1 and _palabras(texto_tabla(candidato)) > palabras_max:
            partes.append(actual)
            actual = [encabezado, fila]
        else:
            actual = candidato
    partes.append(actual)
    return [Bloque(texto_tabla(p), bloque.pagina, filas=p) for p in partes]
