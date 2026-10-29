"""Herramientas deterministas de planificación: horas, semanas, RA y pesos por momento.

Los números no los decide el modelo de lenguaje. La suma de horas de los momentos, por cada
componente, debe coincidir exactamente con las horas oficiales del PF (Propuesta 2026, 7.6:
«control obligatorio de horas»), y los pesos de evaluación deben sumar 100 % dentro de los
rangos orientadores de cada momento.
"""

from syllabusai.esquemas import FichaCurricular
from syllabusai.formato.catalogos import MOMENTOS

# La práctica se concentra donde se ejecuta el desempeño (momento 3), no por proporción pareja.
PROPORCIONES = {
    "horas_contacto": (0.22, 0.26, 0.34, 0.18),
    "horas_practicas": (0.15, 0.25, 0.45, 0.15),
    "horas_autonomas": (0.20, 0.27, 0.33, 0.20),
}
PROPORCION_SEMANAS = (0.20, 0.25, 0.35, 0.20)


def repartir(total: int, proporciones: tuple[float, ...], minimo: int = 0) -> list[int]:
    """Reparto entero cuya suma es exactamente `total` (método del mayor resto)."""
    if total <= 0:
        return [0] * len(proporciones)
    minimo = minimo if total >= minimo * len(proporciones) else 0
    libre = total - minimo * len(proporciones)
    crudos = [libre * p / sum(proporciones) for p in proporciones]
    enteros = [int(c) for c in crudos]
    orden = sorted(range(len(crudos)), key=lambda i: crudos[i] - enteros[i], reverse=True)
    for i in orden[: libre - sum(enteros)]:
        enteros[i] += 1
    return [e + minimo for e in enteros]


def ra_por_momento(n_ra: int, n_momentos: int = 4) -> list[list[str]]:
    """Cada RA se desarrolla en al menos un momento; el último momento integra todos."""
    asignacion = []
    for m in range(n_momentos):
        if m == n_momentos - 1:
            asignacion.append([f"RA{i}" for i in range(1, n_ra + 1)])
        else:
            asignacion.append([f"RA{m * n_ra // n_momentos + 1}"])
    # Un RA que no cayó en los momentos intermedios entra en el momento 3.
    cubiertos = {ra for grupo in asignacion[:-1] for ra in grupo}
    for i in range(1, n_ra + 1):
        if f"RA{i}" not in cubiertos and n_momentos >= 2:
            asignacion[-2].append(f"RA{i}")
    return asignacion


def esqueleto_momentos(
    ficha: FichaCurricular, semanas_periodo: int = 16, pesos: list[int] | None = None
) -> list[dict]:
    """Horas, semanas, RA y peso de cada momento. `pesos` son los que fijó el docente, ya
    completados hasta 100 % (ver `indicaciones.pesos_momentos`); si no hay, los sugeridos."""
    horas = {
        componente: repartir(getattr(ficha, componente), proporciones)
        for componente, proporciones in PROPORCIONES.items()
    }
    semanas = repartir(semanas_periodo, PROPORCION_SEMANAS, minimo=1)
    ras = ra_por_momento(len(ficha.resultados_aprendizaje), len(MOMENTOS))
    esqueleto, inicio = [], 1
    for i, base in enumerate(MOMENTOS):
        fin = inicio + semanas[i] - 1
        esqueleto.append({
            "numero": base.numero,
            "nombre": base.nombre,
            "semanas": f"{inicio}" if fin == inicio else f"{inicio}–{fin}",
            "ra": ras[i],
            "horas_contacto": horas["horas_contacto"][i],
            "horas_practicas": horas["horas_practicas"][i],
            "horas_autonomas": horas["horas_autonomas"][i],
            "peso": pesos[i] if pesos else base.peso_sugerido,
        })
        inicio = fin + 1
    return esqueleto


def momentos_de_ra(esqueleto: list[dict]) -> dict[str, list[int]]:
    resultado: dict[str, list[int]] = {}
    for momento in esqueleto:
        for ra in momento["ra"]:
            resultado.setdefault(ra, []).append(momento["numero"])
    return resultado


def esqueleto_evaluacion(momentos: list[dict]) -> list[dict]:
    """Una evidencia evaluada por momento, con el RA y el peso que fijó la planeación."""
    return [
        {
            "momento": m["numero"],
            "ra": list(m.get("ra", [])),
            "evidencia": (m.get("evaluacion") or {}).get("evidencia") or m.get("evidencia_parcial", ""),
            "peso": (m.get("evaluacion") or {}).get("peso", 0),
        }
        for m in momentos
    ]
