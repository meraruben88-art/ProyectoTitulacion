from pathlib import Path

import yaml

from syllabusai.esquemas import PayloadFragmento
from syllabusai.evaluacion import (
    EVAL,
    es_relevante,
    evaluar_usuarios,
    puntaje_sus,
    recall_y_rr,
    valores,
    verificar,
)


def _fragmento(titulo, ruta, texto):
    return PayloadFragmento(
        fragmento_id="d1-f0001", documento_id=1, tipo_documento="normativa", carrera="TODAS",
        version="1", vigente=True, titulo=titulo, ruta_seccion=ruta, pagina_inicio=1,
        pagina_fin=1, texto=texto,
    )


def test_relevancia_por_documento_y_seccion_o_texto():
    f = _fragmento("Propuesta técnica para el nuevo sílabo", ["7.7. Sistema de evaluación"], "Rúbrica")
    assert es_relevante(f, [{"documento": "propuesta tecnica", "seccion": "7.7. Sistema"}])
    assert es_relevante(f, [{"documento": "Propuesta", "texto": "rubrica"}])
    assert not es_relevante(f, [{"documento": "Modelo Educativo", "texto": "rúbrica"}])


def test_recall_y_rango_reciproco():
    assert recall_y_rr([False, True, False, True, False], 2) == (1.0, 0.5)
    assert recall_y_rr([False] * 5, 3) == (0.0, 0.0)


def test_sus_estandar():
    assert puntaje_sus([5, 1] * 5) == 100.0
    assert puntaje_sus([3] * 10) == 50.0


def test_rutas_y_verificaciones():
    contenido = {"momentos": [{"evaluacion": {"peso": 20, "tipos": ["coevaluacion"]}, "p": "En equipos"},
                              {"evaluacion": {"peso": 80, "tipos": []}, "p": "en equipos de 3"}]}
    assert valores(contenido, "momentos[*].evaluacion.peso") == [20, 80]
    assert valores(contenido, "momentos[1].evaluacion.peso") == [80]
    assert verificar(contenido, {"ruta": "momentos[*].evaluacion.peso", "igual": [20, 80]})[0]
    assert verificar(contenido, {"ruta": "momentos[1].evaluacion.peso", "igual": 80})[0]
    assert verificar(contenido, {"ruta": "momentos[*].p", "contiene": "EQUIPOS"})[0]
    assert not verificar(contenido, {"ruta": "momentos[*].p", "contiene": "de 3"})[0]
    assert verificar(contenido, {"ruta": "momentos[*].evaluacion.tipos", "incluye": "coevaluación"})[0]


def test_archivos_de_evaluacion_son_validos():
    casos = yaml.safe_load((EVAL / "casos_piloto.yaml").read_text(encoding="utf-8"))
    assert 3 <= len(casos["piloto"]) <= 5  # SPEC 11: entre 3 y 5 asignaturas piloto
    for caso in casos["piloto"]:
        for regla in caso["verificar"]:
            assert {"seccion", "ruta"} <= set(regla) and len(regla) == 3, regla
    consultas = yaml.safe_load((EVAL / "consultas_recuperacion.yaml").read_text(encoding="utf-8"))
    assert all(q["relevantes"] for q in consultas["consultas"])
    usuarios = evaluar_usuarios(Path(EVAL / "datos_simulados"))
    assert usuarios["ficticios"] and 0 < usuarios["tiempo"]["reduccion"] < 1
