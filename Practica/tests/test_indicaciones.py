"""El agente atiende lo que pide el docente: preferencias iniciales, indicaciones durante la
revisión, memoria entre secciones y rechazo de cambios a los datos oficiales."""

from conftest import DATOS_GENERALES, ids

from syllabusai.agent.indicaciones import fusionar, interpretar, pesos_momentos


def _seccion(c, silabo_id, clave):
    return next(s for s in c.servicio.estado(silabo_id)["secciones"] if s["clave"] == clave)


def _avanzar_hasta(c, silabo_id, pausa, clave):
    while pausa.get("clave") != clave:
        assert pausa["tipo"] == "revision_seccion", pausa
        pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    return pausa


# --- intérprete -----------------------------------------------------------------------------

def test_interpreta_pedidos_frecuentes():
    r = interpretar("Que trabajen en equipos de 3 y prohíbe la IA. Usa Python y scikit-learn; "
                    "agrega coevaluación")
    assert r.cambios["trabajo"] == "equipos de 3"
    assert r.cambios["politica_ia"] == "prohibida"
    assert r.cambios["tecnologias"] == ["Python", "scikit-learn"]
    assert r.cambios["tipos_evaluacion"] == ["coevaluacion"]
    assert not r.no_entendido

    r = interpretar("quiero que los estudiantes desarrollen un chatbot para la biblioteca")
    assert r.cambios == {"producto": "Un chatbot para la biblioteca"}

    r = interpretar("agrega la referencia: Sommerville, I. (2016). Software Engineering. Pearson.")
    assert r.cambios["bibliografia"] == ["Sommerville, I. (2016). Software Engineering. Pearson."]

    r = interpretar("El problema es que 4 de cada 10 consultas quedan sin respuesta (fuente: informe 2025)")
    assert r.datos["contexto_problema"].startswith("4 de cada 10 consultas")
    assert r.datos["fuentes_problema"] == "Informe 2025"

    # Un pedido escrito a continuación del problema, en la misma línea, no se pierde.
    r = interpretar("El problema es que el 38 % se atiende tarde (fuente: informe A25). Prohíbe la IA.")
    assert r.datos["contexto_problema"] == "El 38 % se atiende tarde"
    assert r.cambios["politica_ia"] == "prohibida"


def test_rechaza_cambiar_datos_oficiales_y_avisa_lo_que_no_entiende():
    r = interpretar("cambia el RA1 para que sea más fácil")
    assert r.rechazado and "Comité Curricular" in r.rechazado[0] and not r.cambios
    r = interpretar("me gusta el color azul")
    assert r.no_entendido == ["me gusta el color azul"]


def test_fusionar_recuerda_y_quita():
    prefs = fusionar({}, interpretar("usa Python, Docker y Git"))
    prefs = fusionar(prefs, interpretar("sin Docker"))
    assert prefs["tecnologias"] == ["Python", "Git"]


def test_pesos_respetan_lo_pedido_y_suman_100():
    pesos, aviso = pesos_momentos({"3": 30, "1": 25})
    assert pesos[0] == 25 and pesos[2] == 30 and sum(pesos) == 100 and aviso is None
    pesos, aviso = pesos_momentos({"1": 80, "2": 30})
    assert sum(pesos) == 100 and aviso


# --- agente completo --------------------------------------------------------------------------

def test_el_agente_construye_el_silabo_con_lo_que_pide_el_docente(contenedor):
    c = contenedor
    asignatura_id, docente_id = ids(c)
    referencia = "Chollet, F. (2021). Deep Learning with Python (2nd ed.). Manning."
    datos = DATOS_GENERALES | {
        "preferencias": {"producto": "Un asistente conversacional que oriente a los estudiantes "
                                     "nuevos", "tecnologias": ["Python"], "bibliografia": [referencia]},
        "indicaciones_generales": "Que trabajen en equipos de 3. Agrega coevaluación.",
    }
    silabo_id = c.servicio.crear_silabo(docente_id, asignatura_id, "B26", datos)
    estado = c.servicio.estado(silabo_id)
    assert "modalidad de trabajo: equipos de 3" in estado["preferencias"]
    assert estado["datos_generales"]["interpretacion_inicial"]["entendido"]

    _avanzar_hasta(c, silabo_id, c.orquestador.iniciar(silabo_id), "problema_reto")
    reto = _seccion(c, silabo_id, "problema_reto")["contenido"]
    assert "asistente conversacional" in reto["pregunta_reto"]
    assert "Python" in reto["producto_integrador"]

    # Durante la revisión, el docente pide algo que corresponde a una sección posterior: el
    # agente lo recuerda y lo aplica al llegar a ella.
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "regenerar",
                                               "indicacion": "prohíbe la IA y usa scikit-learn"})
    nota = _seccion(c, silabo_id, "problema_reto")["nota"]
    assert "Lo tendré en cuenta en: 7.5 Contenidos; 7.6 Planeación" in nota

    pausa = _avanzar_hasta(c, silabo_id, pausa, "planeacion_momentos")
    momentos = _seccion(c, silabo_id, "planeacion_momentos")["contenido"]["momentos"]
    assert all(m["politica_ia"].startswith("No aplica") for m in momentos)
    assert all("equipos de 3 estudiantes" in m["practico_experimental"] for m in momentos)
    assert all("scikit-learn" in m["practico_experimental"] for m in momentos)
    assert all("coevaluacion" in m["evaluacion"]["tipos"] for m in momentos)

    # Pesos a pedido: se respetan y la suma sigue cuadrando.
    pausa = c.orquestador.reanudar(silabo_id, {"accion": "regenerar",
                                               "indicacion": "momento 3 con 30% y momento 1 con 25%"})
    momentos = _seccion(c, silabo_id, "planeacion_momentos")["contenido"]["momentos"]
    pesos = [m["evaluacion"]["peso"] for m in momentos]
    assert pesos[0] == 25 and pesos[2] == 30 and sum(pesos) == 100

    pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    assert pausa["clave"] == "evaluacion"
    pausa = c.orquestador.reanudar(silabo_id, {
        "accion": "regenerar", "indicacion": "agrega el criterio: el asistente responde en menos de 3 s"})
    evidencias = _seccion(c, silabo_id, "evaluacion")["contenido"]["evidencias"]
    assert evidencias[0]["criterios"][0] == "El asistente responde en menos de 3 s"
    assert len(evidencias[0]["criterios"]) <= 4
    assert [e["peso"] for e in evidencias] == pesos

    pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    recursos = _seccion(c, silabo_id, "recursos")["contenido"]
    assert recursos["bibliografia_basica"][0] == referencia  # la del docente se conserva
    assert "No se autoriza" in recursos["tecnologia_ia"]

    while pausa["tipo"] == "revision_seccion":
        pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    assert pausa == {"tipo": "terminado"}
    assert c.servicio.exportar(silabo_id, "docx").exists()


def test_el_docente_completa_el_problema_conversando(contenedor):
    c = contenedor
    asignatura_id, docente_id = ids(c)
    silabo_id = c.servicio.crear_silabo(docente_id, asignatura_id, "B26",
                                        DATOS_GENERALES | {"contexto_problema": ""})
    _avanzar_hasta(c, silabo_id, c.orquestador.iniciar(silabo_id), "problema_reto")
    seccion = _seccion(c, silabo_id, "problema_reto")
    assert seccion["estado"] == "abstenida" and "El problema es que" in seccion["nota"]

    c.orquestador.reanudar(silabo_id, {"accion": "regenerar", "indicacion": (
        "El problema es que el 40 % de las consultas de la biblioteca llegan fuera de horario "
        "(fuente: Informe de biblioteca 2025)")})
    seccion = _seccion(c, silabo_id, "problema_reto")
    assert seccion["estado"] == "propuesta"
    assert seccion["contenido"]["problema"].startswith("El 40 % de las consultas")


def test_pedir_cambiar_un_ra_no_lo_cambia(contenedor):
    c = contenedor
    asignatura_id, docente_id = ids(c)
    silabo_id = c.servicio.crear_silabo(docente_id, asignatura_id, "B26", dict(DATOS_GENERALES))
    _avanzar_hasta(c, silabo_id, c.orquestador.iniciar(silabo_id), "resultados_aprendizaje")
    original = _seccion(c, silabo_id, "resultados_aprendizaje")["contenido"]["resultados"][0]["enunciado"]
    c.orquestador.reanudar(silabo_id, {"accion": "regenerar", "indicacion": "elimina el RA1"})
    seccion = _seccion(c, silabo_id, "resultados_aprendizaje")
    assert seccion["contenido"]["resultados"][0]["enunciado"] == original
    assert "Comité Curricular" in seccion["nota"]
