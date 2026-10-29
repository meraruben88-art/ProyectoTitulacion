import copy

import pytest

from syllabusai.agent.planificacion import esqueleto_momentos, ra_por_momento, repartir
from syllabusai.agent.servicio import aplicar_bloqueos
from syllabusai.esquemas import FichaCurricular
from syllabusai.formato.catalogos import EJES, METACOMPETENCIAS
from syllabusai.validation.reglas import validar_seccion

FICHA = FichaCurricular(
    horas_contacto=72, horas_practicas=26, horas_autonomas=46,
    resultados_aprendizaje=[{"codigo": "RA1", "enunciado": "Analiza problemas."},
                            {"codigo": "RA2", "enunciado": "Desarrolla modelos."}],
    contenidos_minimos=["Búsqueda", "Aprendizaje automático", "Ética de la IA"],
    competencia_especifica="PE-PP-04 -- Desarrolla aplicaciones.",
)


def reglas_de(hallazgos):
    return {h.regla for h in hallazgos}


@pytest.mark.parametrize("total", [0, 1, 7, 144, 145])
def test_repartir_suma_exacta(total):
    assert sum(repartir(total, (0.22, 0.26, 0.34, 0.18))) == total


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_todo_ra_queda_en_algun_momento(n):
    cubiertos = {ra for grupo in ra_por_momento(n) for ra in grupo}
    assert cubiertos == {f"RA{i}" for i in range(1, n + 1)}


def test_esqueleto_cuadra_horas_y_pesos():
    esqueleto = esqueleto_momentos(FICHA, 16)
    assert sum(m["horas_contacto"] for m in esqueleto) == 72
    assert sum(m["horas_practicas"] for m in esqueleto) == 26
    assert sum(m["horas_autonomas"] for m in esqueleto) == 46
    assert sum(m["peso"] for m in esqueleto) == 100
    assert esqueleto[0]["semanas"].startswith("1") and esqueleto[-1]["semanas"].endswith("16")


def _planeacion():
    momentos = []
    for m in esqueleto_momentos(FICHA, 16):
        momentos.append(m | {
            "proposito": "p", "contacto_docente": "c", "aprendizaje_autonomo": "a",
            "practico_experimental": "e", "evidencia_parcial": "ev", "politica_ia": "No aplica",
            "retroalimentacion": "r", "contenidos_conceptuales": FICHA.contenidos_minimos,
            "evaluacion": {"evidencia": "ev", "peso": m.pop("peso"), "tipos": ["heteroevaluacion"],
                           "instrumento": "Rúbrica"},
        })
    return {"momentos": momentos}


def test_planeacion_valida_no_tiene_hallazgos():
    assert validar_seccion("planeacion_momentos", _planeacion(), FICHA) == []


def test_horas_que_no_cuadran_bloquean():
    plan = _planeacion()
    plan["momentos"][0]["horas_practicas"] += 1
    plan["momentos"][1]["evaluacion"]["peso"] += 5
    hallazgos = validar_seccion("planeacion_momentos", plan, FICHA)
    assert {h.regla for h in hallazgos if h.severidad == "bloqueante"} == {"RF-34"}


def test_ra_alterado_o_sin_evidencia_bloquea():
    contenido = {"resultados": [
        {"codigo": "RA1", "enunciado": "Conoce problemas.", "evidencia": "Informe", "momentos": [1]},
        {"codigo": "RA2", "enunciado": "Desarrolla modelos.", "evidencia": "", "momentos": [2]},
    ]}
    hallazgos = validar_seccion("resultados_aprendizaje", contenido, FICHA)
    assert any(h.regla == "CUR-01" and "RA1" in h.mensaje for h in hallazgos)
    assert any(h.regla == "RF-33" and "RA2" in h.mensaje for h in hallazgos)


def test_contenido_minimo_eliminado_bloquea():
    contenido = {"contenidos_minimos": FICHA.contenidos_minimos[:2], "conceptuales": ["a"],
                 "procedimentales": ["b"], "actitudinales": ["c"]}
    hallazgos = validar_seccion("contenidos", contenido, FICHA)
    assert [h.regla for h in hallazgos] == ["CUR-01"] and "Ética" in hallazgos[0].mensaje


def test_anclaje_con_listas_cerradas():
    contenido = {
        "competencia_especifica": FICHA.competencia_especifica, "desempeno_central": "Comprender IA",
        "metacompetencia": "Otra inventada", "habilidades_blandas": ["Liderazgo"],
        "ejes": [{"eje": EJES[0], "justificacion": ""}], "accesibilidad_nee": "x",
        "articulacion_pf": "y", "pis_periodo": "PIS 5", "aporte_pis": None,
    }
    reglas = reglas_de(validar_seccion("anclaje_curricular", contenido, FICHA))
    assert {"FMT-01", "FMT-03", "FMT-06"} <= reglas
    contenido |= {"metacompetencia": METACOMPETENCIAS[0], "desempeno_central": "Desarrolla IA",
                  "aporte_pis": "RA2 y producto", "ejes": [{"eje": EJES[0], "justificacion": "M3"}]}
    assert validar_seccion("anclaje_curricular", contenido, FICHA) == []


def test_marcadores_de_plantilla_sin_completar():
    contenido = {"problema": "[Describir la situación]", "pregunta_reto": "¿Cómo podemos x?",
                 "producto_integrador": "p", "escenario_actores": "e", "criterio_impacto": "c"}
    reglas = reglas_de(validar_seccion("problema_reto", contenido, FICHA, {"fuentes_problema": "f"}))
    assert reglas == {"RF-31"}


def test_bloqueos_restituyen_datos_oficiales():
    contexto = {"ficha": FICHA.model_dump(mode="json"), "momentos_de_ra": {"RA1": [1], "RA2": [3]}}
    propuesta = {"resultados": [
        {"codigo": "RA1", "enunciado": "Reescrito por el modelo", "evidencia": "Informe", "momentos": []},
    ]}
    contenido, avisos = aplicar_bloqueos("resultados_aprendizaje", copy.deepcopy(propuesta), contexto)
    assert [r["enunciado"] for r in contenido["resultados"]] == ["Analiza problemas.", "Desarrolla modelos."]
    assert contenido["resultados"][0]["momentos"] == [1]
    assert avisos and avisos[0].regla == "CUR-01"


def test_bloqueo_retira_bibliografia_inventada():
    contexto = {"ficha": FICHA.model_dump(mode="json"),
                "candidatos_bibliografia": ["Russell, S., & Norvig, P. (2021). AIMA. Pearson."]}
    propuesta = {"bibliografia_basica": ["Russell, S., & Norvig, P. (2021). AIMA. Pearson.",
                                         "Autor Inventado (2024). Libro que no existe."]}
    contenido, avisos = aplicar_bloqueos("recursos", propuesta, contexto)
    assert contenido["bibliografia_basica"] == ["Russell, S., & Norvig, P. (2021). AIMA. Pearson."]
    assert avisos[0].regla == "RF-13"
