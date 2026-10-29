"""Conjunto cerrado de herramientas del agente (RF-22, SPEC 7.2).

El modelo no tiene acceso a Internet, al sistema de archivos ni a nada fuera de esta lista. Las
herramientas de consulta devuelven fragmentos filtrados por tipo de documento, carrera y
vigencia; las de planificación son deterministas (ver `planificacion.py`).
"""

import re

from syllabusai.db.modelos import TipoDocumento as T
from syllabusai.formato.definicion import DefinicionSeccion
from syllabusai.retrieval.lexico import normalizar
from syllabusai.retrieval.recuperador import FragmentoRecuperado, Recuperador, Registro

# Tipos de documento que consulta cada herramienta de recuperación.
TIPOS_POR_HERRAMIENTA: dict[str, list[T]] = {
    "consultar_normativa": [T.NORMATIVA, T.PLANTILLA],
    "identificar_competencias": [T.PERFIL_EGRESO],
    "obtener_contenidos_minimos": [T.MALLA, T.CONTENIDOS_MINIMOS],
    "buscar_silabos_ejemplo": [T.SILABO_APROBADO],
    "buscar_bibliografia": [T.MALLA, T.CONTENIDOS_MINIMOS, T.SILABO_APROBADO],
}

MAX_FRAGMENTOS_SECCION = 10


def recuperar_evidencia(
    recuperador: Recuperador,
    definicion: DefinicionSeccion,
    variables: dict[str, str],
    tipos_extra: list[T] | None = None,
    registro: Registro | None = None,
) -> list[FragmentoRecuperado]:
    """Ejecuta las consultas de la sección con sus herramientas y deduplica los fragmentos."""
    tipos = []
    for herramienta in definicion.herramientas:
        for tipo in TIPOS_POR_HERRAMIENTA.get(herramienta, []):
            if tipo not in tipos:
                tipos.append(tipo)
    for tipo in list(definicion.tipos_requeridos) + list(tipos_extra or []):
        if tipo not in tipos:
            tipos.append(tipo)
    if not tipos:
        return []

    vistos: dict[str, FragmentoRecuperado] = {}
    for plantilla in definicion.consultas:
        consulta = plantilla.format_map(_Faltante(variables))
        # Cada tipo requerido se consulta por separado para que un documento extenso (el
        # Modelo Educativo) no desplace a los demás en el top-k.
        grupos = [[t] for t in definicion.tipos_requeridos] + [tipos]
        for grupo in grupos:
            for r in recuperador.buscar(
                consulta, tipos=grupo, carrera=variables.get("carrera"), registro=registro
            ):
                actual = vistos.get(r.fragmento.fragmento_id)
                if actual is None or r.puntaje_lexico > actual.puntaje_lexico:
                    vistos[r.fragmento.fragmento_id] = r
    ordenados = sorted(vistos.values(), key=lambda r: r.puntaje_lexico, reverse=True)
    # Los mejores fragmentos de cada tipo requerido se conservan aunque otros puntúen más.
    elegidos = []
    for tipo in definicion.tipos_requeridos:
        elegidos += [r for r in ordenados if r.fragmento.tipo_documento == tipo][:2]
    for r in ordenados:
        if len(elegidos) >= MAX_FRAGMENTOS_SECCION:
            break
        if r not in elegidos:
            elegidos.append(r)
    return elegidos


class _Faltante(dict):
    def __missing__(self, clave: str) -> str:
        return ""


def evidencia_suficiente(
    fragmentos: list[FragmentoRecuperado], requeridos: list[T], minimo: int
) -> list[T]:
    """Tipos requeridos que no alcanzan el mínimo de fragmentos con coincidencia léxica."""
    faltan = []
    for tipo in requeridos:
        n = sum(1 for f in fragmentos if f.fragmento.tipo_documento == tipo and f.puntaje_lexico > 0)
        if n < minimo:
            faltan.append(tipo)
    return faltan


_ANIO = re.compile(r"\((19|20)\d{2}[a-z]?\)|\b(19|20)\d{2}\b")


def candidatos_bibliografia(
    ficha_bibliografia: list[str], fragmentos: list[FragmentoRecuperado], asignatura: str
) -> list[str]:
    """Referencias que existen en la ficha o en los documentos; el modelo solo elige entre ellas.

    De los documentos solo se toman las referencias de fragmentos que mencionan la asignatura,
    para no proponer la bibliografía de otra asignatura de la misma malla.
    """
    candidatos = list(ficha_bibliografia)
    nombre = normalizar(asignatura)
    for r in fragmentos:
        f = r.fragmento
        if f.tipo_documento not in TIPOS_POR_HERRAMIENTA["buscar_bibliografia"]:
            continue
        contexto = normalizar(" ".join(f.ruta_seccion))
        if nombre not in contexto and nombre not in normalizar(f.texto):
            continue
        for linea in re.split(r"\n|\s\|\s", f.texto):
            linea = linea.strip(" -•\t")
            parece_referencia = len(linea) > 25 and _ANIO.search(linea) and (
                "bibliograf" in contexto or "." in linea
            )
            if parece_referencia and linea not in candidatos:
                candidatos.append(linea)
    return candidatos

