"""Reglas de validación del sílabo (RF-30 a RF-36) y de la lista de verificación de la
Propuesta 2026 (sección 11).

Cada regla devuelve hallazgos con severidad: los bloqueantes impiden la exportación final; las
advertencias puede descartarlas el docente con una justificación. Los identificadores de regla
remiten al SPEC (RF-xx) o a la Propuesta 2026 (CUR = datos curriculares bloqueados,
FMT = reglas del formato).
"""

import re
from dataclasses import dataclass
from typing import Any

from syllabusai.db.modelos import EstadoSeccion, Severidad
from syllabusai.esquemas import FichaCurricular
from syllabusai.formato.catalogos import (
    EJES,
    METACOMPETENCIAS,
    MOMENTOS,
    TIPOS_EVALUACION,
    VERBOS_TEMATICOS,
)
from syllabusai.formato.esquemas import ESQUEMAS
from syllabusai.retrieval.lexico import normalizar

B, A = Severidad.BLOQUEANTE, Severidad.ADVERTENCIA


@dataclass(frozen=True)
class Hallazgo:
    regla: str
    severidad: Severidad
    mensaje: str
    clave: str | None = None  # sección afectada; None si afecta al sílabo completo


# Campos que no pueden quedar vacíos en cada sección (RF-31).
REQUERIDOS = {
    "identificacion": ["nombre_pf", "codigo", "carrera", "nivel", "modalidad",
                       "periodo_academico", "docente"],
    "anclaje_curricular": ["competencia_especifica", "desempeno_central", "metacompetencia",
                           "habilidades_blandas", "ejes", "accesibilidad_nee", "articulacion_pf"],
    "problema_reto": ["problema", "pregunta_reto", "producto_integrador", "escenario_actores",
                      "criterio_impacto"],
    "resultados_aprendizaje": ["resultados"],
    "contenidos": ["contenidos_minimos", "conceptuales", "procedimentales", "actitudinales"],
    "planeacion_momentos": ["momentos"],
    "evaluacion": ["evidencias"],
    "recursos": ["bibliografia_basica", "tecnologia_ia", "escenarios", "accesibilidad"],
    "seguimiento_mejora": ["registro_logro_ra", "acciones_mejora", "ajustes_siguiente_periodo"],
}

REQUERIDOS_MOMENTO = ["semanas", "ra", "proposito", "contacto_docente", "aprendizaje_autonomo",
                      "practico_experimental", "evidencia_parcial", "politica_ia",
                      "retroalimentacion"]

# Secciones generadas que deben citar al menos una fuente vigente (RF-32).
CON_EVIDENCIA = {"anclaje_curricular", "resultados_aprendizaje", "contenidos",
                 "planeacion_momentos", "evaluacion", "recursos"}

_MARCADOR = re.compile(r"\[[^\]]{0,80}\]")  # «[IMPORTAR]», «[ ]», «[RA…]» sin reemplazar


def _vacio(valor: Any) -> bool:
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip()
    if isinstance(valor, (list, dict)):
        return len(valor) == 0
    return False


def _norm(texto: str) -> str:
    return " ".join(normalizar(texto).split())


def _textos(valor: Any):
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _textos(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _textos(v)


# --- reglas por sección -------------------------------------------------------------------

def validar_seccion(
    clave: str, contenido: dict, ficha: FichaCurricular, datos: dict | None = None
) -> list[Hallazgo]:
    datos = datos or {}
    hallazgos = []
    try:
        ESQUEMAS[clave].model_validate(contenido)
    except Exception as error:  # noqa: BLE001 — pydantic.ValidationError con detalle legible
        return [Hallazgo("RF-31", B, f"El contenido no cumple el esquema de la sección: {error}", clave)]

    for campo in REQUERIDOS.get(clave, []):
        if _vacio(contenido.get(campo)):
            hallazgos.append(Hallazgo("RF-31", B, f"Campo obligatorio vacío: «{campo}».", clave))
    for texto in _textos(contenido):
        if _MARCADOR.search(texto):
            hallazgos.append(Hallazgo(
                "RF-31", B, f"Quedan marcadores sin completar: «{_MARCADOR.search(texto).group()}».",
                clave,
            ))
            break

    revisor = _REGLAS_SECCION.get(clave)
    if revisor:
        hallazgos += revisor(contenido, ficha, datos)
    return hallazgos


def _identificacion(c: dict, ficha: FichaCurricular, datos: dict) -> list[Hallazgo]:
    h = []
    oficiales = {"horas_contacto": ficha.horas_contacto, "horas_practicas": ficha.horas_practicas,
                 "horas_autonomas": ficha.horas_autonomas, "total_horas": ficha.total_horas}
    for campo, valor in oficiales.items():
        if c.get(campo) != valor:
            h.append(Hallazgo("CUR-01", B, f"«{campo}» ({c.get(campo)}) no coincide con la malla "
                              f"aprobada ({valor}). Los datos curriculares no se modifican en el "
                              "sílabo: escale la discrepancia al Comité Curricular.", "identificacion"))
    if c.get("horas_contacto", 0) + c.get("horas_practicas", 0) + c.get("horas_autonomas", 0) != c.get("total_horas"):
        h.append(Hallazgo("RF-34", B, "El total de horas no es la suma de los componentes.",
                          "identificacion"))
    return h


def _anclaje(c: dict, ficha: FichaCurricular, datos: dict) -> list[Hallazgo]:
    h = []
    k = "anclaje_curricular"
    if ficha.competencia_especifica and _norm(c.get("competencia_especifica", "")) != _norm(ficha.competencia_especifica):
        h.append(Hallazgo("CUR-01", B, "La competencia específica debe transcribirse sin modificar "
                          "desde la matriz PF ↔ perfil aprobada.", k))
    for campo in ("metacompetencia", "metacompetencia_secundaria"):
        valor = c.get(campo)
        if valor and valor not in METACOMPETENCIAS:
            h.append(Hallazgo("FMT-01", B, f"«{valor}» no es una de las cinco metacompetencias "
                              "institucionales.", k))
    if c.get("metacompetencia") and c.get("metacompetencia") == c.get("metacompetencia_secundaria"):
        h.append(Hallazgo("FMT-01", A, "La metacompetencia secundaria repite la prioritaria.", k))
    for eje in c.get("ejes", []):
        if eje.get("eje") not in EJES:
            h.append(Hallazgo("FMT-01", B, f"«{eje.get('eje')}» no es un eje del Modelo Educativo.", k))
        if _vacio(eje.get("justificacion")):
            h.append(Hallazgo("FMT-01", A, f"El eje «{eje.get('eje')}» no indica en qué actividad o "
                              "evidencia se concreta.", k))
    desempeno = normalizar(c.get("desempeno_central", ""))
    if desempeno.split()[:1] and desempeno.split()[0] in VERBOS_TEMATICOS:
        h.append(Hallazgo("FMT-03", A, "El desempeño central empieza con un verbo temático; use un "
                          "verbo de actuación de mediana o alta complejidad.", k))
    if c.get("pis_periodo") and _vacio(c.get("aporte_pis")):
        h.append(Hallazgo("FMT-06", B, "Hay PIS en el periodo pero no se declara el aporte del PF "
                          "(RA y producto/evidencia).", k))
    return h


def _problema(c: dict, ficha: FichaCurricular, datos: dict) -> list[Hallazgo]:
    h = []
    reto = c.get("pregunta_reto", "").strip()
    if reto and not (normalizar(reto).startswith("¿como") and reto.endswith("?")):
        h.append(Hallazgo("FMT-02", A, "La pregunta reto no sigue la fórmula «¿Cómo podemos + "
                          "acción + objeto + contexto + beneficio?».", "problema_reto"))
    if _vacio(datos.get("fuentes_problema")):
        h.append(Hallazgo("FMT-07", A, "El problema del territorio debe documentarse con datos y "
                          "fuentes verificables; registre las fuentes en los datos generales.",
                          "problema_reto"))
    return h


def _resultados(c: dict, ficha: FichaCurricular, datos: dict) -> list[Hallazgo]:
    h, k = [], "resultados_aprendizaje"
    resultados = c.get("resultados", [])
    if not 1 <= len(resultados) <= 4:
        h.append(Hallazgo("CUR-02", B, f"El PF debe tener entre 1 y 4 RA; tiene {len(resultados)}.", k))
    oficiales = {r.codigo: r.enunciado for r in ficha.resultados_aprendizaje}
    propios = {r.get("codigo"): r for r in resultados}
    for codigo, enunciado in oficiales.items():
        ra = propios.get(codigo)
        if ra is None:
            h.append(Hallazgo("CUR-01", B, f"Falta el {codigo} oficial de la malla.", k))
        elif _norm(ra.get("enunciado", "")) != _norm(enunciado):
            h.append(Hallazgo("CUR-01", B, f"El enunciado del {codigo} no coincide con el aprobado "
                              "en la malla. Transcríbalo sin cambios o escale la reforma al Comité "
                              "Curricular.", k))
    for codigo in set(propios) - set(oficiales):
        h.append(Hallazgo("CUR-01", B, f"{codigo} no existe en la malla aprobada.", k))
    for ra in resultados:
        if _vacio(ra.get("evidencia")):
            h.append(Hallazgo("RF-33", B, f"{ra.get('codigo')} no tiene evidencia observable.", k))
        if _vacio(ra.get("momentos")):
            h.append(Hallazgo("RF-33", B, f"{ra.get('codigo')} no se asigna a ningún momento.", k))
    return h


def _contenidos(c: dict, ficha: FichaCurricular, datos: dict) -> list[Hallazgo]:
    presentes = {_norm(x) for x in c.get("contenidos_minimos", [])}
    return [
        Hallazgo("CUR-01", B, f"Falta o se alteró el contenido mínimo oficial «{m}». No se "
                 "elimina un contenido mínimo desde el sílabo.", "contenidos")
        for m in ficha.contenidos_minimos if _norm(m) not in presentes
    ]


def _momentos(c: dict, ficha: FichaCurricular, datos: dict) -> list[Hallazgo]:
    h, k = [], "planeacion_momentos"
    momentos = c.get("momentos", [])
    oficiales = {r.codigo for r in ficha.resultados_aprendizaje}
    for m in momentos:
        n = m.get("numero")
        for campo in REQUERIDOS_MOMENTO:
            if _vacio(m.get(campo)):
                h.append(Hallazgo("RF-31", B, f"Momento {n}: campo vacío «{campo}».", k))
        for ra in m.get("ra", []):
            if ra not in oficiales:
                h.append(Hallazgo("RF-33", B, f"Momento {n} declara {ra}, que no es un RA del PF.", k))
        tipos = (m.get("evaluacion") or {}).get("tipos", [])
        if any(t not in TIPOS_EVALUACION for t in tipos):
            h.append(Hallazgo("FMT-05", A, f"Momento {n}: tipo de evaluación no reconocido.", k))
    for componente, oficial in (("horas_contacto", ficha.horas_contacto),
                                ("horas_practicas", ficha.horas_practicas),
                                ("horas_autonomas", ficha.horas_autonomas)):
        suma = sum(m.get(componente, 0) for m in momentos)
        if suma != oficial:
            h.append(Hallazgo("RF-34", B, f"Las {componente.replace('_', ' ')} de los momentos "
                              f"suman {suma} y las oficiales son {oficial}.", k))
    pesos = sum((m.get("evaluacion") or {}).get("peso", 0) for m in momentos)
    if momentos and pesos != 100:
        h.append(Hallazgo("RF-34", B, f"Los pesos de evaluación de los momentos suman {pesos} %.", k))
    rangos = {b.numero: b for b in MOMENTOS}
    for m in momentos:
        base, peso = rangos.get(m.get("numero")), (m.get("evaluacion") or {}).get("peso", 0)
        if base and not base.peso_min <= peso <= base.peso_max:
            h.append(Hallazgo("RF-34", A, f"Momento {m.get('numero')}: peso {peso} % fuera del rango "
                              f"orientador {base.peso_min}–{base.peso_max} %.", k))
    distribuidos = _norm(" ".join(_textos([m.get("contenidos_conceptuales", []) for m in momentos])))
    for minimo in ficha.contenidos_minimos:
        if _norm(minimo)[:40] not in distribuidos:
            h.append(Hallazgo("RF-33", A, f"El contenido mínimo «{minimo}» no aparece distribuido "
                              "en ningún momento.", k))
    return h


def _evaluacion(c: dict, ficha: FichaCurricular, datos: dict) -> list[Hallazgo]:
    h, k = [], "evaluacion"
    evidencias = c.get("evidencias", [])
    oficiales = {r.codigo for r in ficha.resultados_aprendizaje}
    total = sum(e.get("peso", 0) for e in evidencias)
    if evidencias and total != 100:
        h.append(Hallazgo("RF-34", B, f"Los porcentajes de evaluación suman {total} %, no 100 %.", k))
    cubiertos = {ra for e in evidencias for ra in e.get("ra", [])}
    for ra in sorted(oficiales - cubiertos):
        h.append(Hallazgo("RF-33", B, f"{ra} no tiene evidencia ni instrumento de evaluación.", k))
    for e in evidencias:
        for ra in e.get("ra", []):
            if ra not in oficiales:
                h.append(Hallazgo("RF-33", B, f"Evidencia huérfana: {ra} no es un RA del PF.", k))
        if not 2 <= len(e.get("criterios", [])) <= 4:
            h.append(Hallazgo("FMT-05", A, f"La evidencia del momento {e.get('momento')} debe tener "
                              "entre 2 y 4 criterios observables.", k))
        if _vacio(e.get("instrumento")) or _vacio(e.get("oportunidad_mejora")):
            h.append(Hallazgo("RF-31", B, f"La evidencia del momento {e.get('momento')} no declara "
                              "instrumento u oportunidad de mejora.", k))
    return h


_REGLAS_SECCION = {
    "identificacion": _identificacion,
    "anclaje_curricular": _anclaje,
    "problema_reto": _problema,
    "resultados_aprendizaje": _resultados,
    "contenidos": _contenidos,
    "planeacion_momentos": _momentos,
    "evaluacion": _evaluacion,
}


# --- reglas del sílabo completo -----------------------------------------------------------

@dataclass
class EstadoSeccionValidable:
    clave: str
    estado: EstadoSeccion
    contenido: dict
    citas_validas: int  # citas a fragmentos vigentes
    citas_obsoletas: int
    # El docente escribió la sección sin propuesta citada del agente (p. ej. tras una abstención).
    redactada_por_docente: bool = False


def sin_fuentes(clave: str, redactada_por_docente: bool) -> Hallazgo:
    """Una propuesta del agente sin fuentes bloquea (RF-32). Lo que el docente escribe por su
    cuenta es responsabilidad suya: se advierte y puede descartarse con justificación."""
    if redactada_por_docente:
        return Hallazgo("RF-32", A, "Sección redactada por el docente sin fuentes del corpus: verifique "
                        "sus referencias o justifique.", clave)
    return Hallazgo("RF-32", B, "La sección no tiene ninguna fuente vigente asociada.", clave)


def validar_silabo(
    claves_formato: list[str],
    secciones: dict[str, EstadoSeccionValidable],
    ficha: FichaCurricular,
    datos: dict | None = None,
) -> list[Hallazgo]:
    hallazgos = []
    for clave in claves_formato:
        seccion = secciones.get(clave)
        if seccion is None:
            hallazgos.append(Hallazgo("RF-30", B, f"Falta la sección «{clave}» del formato."))
            continue
        if seccion.estado != EstadoSeccion.APROBADA:
            hallazgos.append(Hallazgo("RF-30", B, "La sección no está aprobada por el docente.", clave))
        hallazgos += validar_seccion(clave, seccion.contenido, ficha, datos)
        if clave in CON_EVIDENCIA and seccion.citas_validas == 0:
            hallazgos.append(sin_fuentes(clave, seccion.redactada_por_docente))
        if seccion.citas_obsoletas:
            hallazgos.append(Hallazgo("RF-32", B, f"La sección cita {seccion.citas_obsoletas} "
                                      "fragmento(s) de documentos obsoletos.", clave))
    hallazgos += _coherencia_cruzada(secciones, ficha)
    return hallazgos


def _coherencia_cruzada(secciones: dict[str, EstadoSeccionValidable], ficha) -> list[Hallazgo]:
    """La misma evidencia y los mismos RA deben aparecer en RA, planeación y evaluación."""
    h = []
    contenido = {k: s.contenido for k, s in secciones.items()}
    momentos = contenido.get("planeacion_momentos", {}).get("momentos", [])
    evaluadas = contenido.get("evaluacion", {}).get("evidencias", [])
    en_momentos = {ra for m in momentos for ra in m.get("ra", [])}
    for ra in contenido.get("resultados_aprendizaje", {}).get("resultados", []):
        if momentos and ra.get("codigo") not in en_momentos:
            h.append(Hallazgo("RF-33", B, f"{ra.get('codigo')} no se desarrolla en ningún momento "
                              "de la planeación.", "planeacion_momentos"))
        faltan = set(ra.get("momentos", [])) - {m.get("numero") for m in momentos}
        if momentos and faltan:
            h.append(Hallazgo("RF-33", A, f"{ra.get('codigo')} declara momentos inexistentes: "
                              f"{sorted(faltan)}.", "resultados_aprendizaje"))
    pesos_momentos = {m.get("numero"): (m.get("evaluacion") or {}).get("peso") for m in momentos}
    for e in evaluadas:
        if pesos_momentos and pesos_momentos.get(e.get("momento")) != e.get("peso"):
            h.append(Hallazgo("RF-34", B, f"El peso de la evidencia del momento {e.get('momento')} "
                              "no coincide con el de la planeación.", "evaluacion"))
    return h
