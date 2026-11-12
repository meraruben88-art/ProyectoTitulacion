"""Página web: sesiones, cuentas, noticias con RAG, PIS, documento final y exportación."""

import pytest
from conftest import DATOS_GENERALES, escribir_normativa, ids
from fastapi.testclient import TestClient

from syllabusai.api.app import crear_app

WEB = {"X-SyllabusAI-Web": "1"}


@pytest.fixture
def cliente(contenedor):
    return TestClient(crear_app(lambda: contenedor))


def entrar(cliente, correo, clave):
    r = cliente.post("/web/login", json={"correo": correo, "clave": clave})
    assert r.status_code == 200, r.text
    return r.json()


def _silabo_terminado(c):
    asignatura_id, docente_id = ids(c)
    silabo_id = c.servicio.crear_silabo(docente_id, asignatura_id, "B26", dict(DATOS_GENERALES))
    pausa = c.orquestador.iniciar(silabo_id)
    while pausa["tipo"] == "revision_seccion":
        pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    assert pausa == {"tipo": "terminado"}
    return silabo_id


def test_sesion_web_con_cookie(cliente):
    assert cliente.post("/web/login", json={"correo": "docente@uti.test", "clave": "mala"}).status_code == 401
    # Sin sesión, la web no recibe el desafío de autenticación básica (no abre el diálogo).
    r = cliente.get("/web/yo", headers=WEB)
    assert r.status_code == 401 and "www-authenticate" not in r.headers
    usuario = entrar(cliente, "DOCENTE@uti.test ", "docente")
    assert usuario["rol"] == "docente"
    assert cliente.get("/web/yo").json()["correo"] == "docente@uti.test"
    assert cliente.get("/silabos").status_code == 200  # la API de sílabos acepta la cookie
    cliente.post("/web/logout")
    assert cliente.get("/web/yo", headers=WEB).status_code == 401


def test_administrador_crea_y_desactiva_docentes(cliente):
    entrar(cliente, "admin@uti.test", "admin")
    r = cliente.post("/web/usuarios", json={"nombre": "Ana Pérez", "correo": "aperez@uti.test", "carrera": "ITI"})
    assert r.status_code == 200, r.text
    nueva = r.json()
    assert len(nueva["clave_temporal"]) == 12
    lote = cliente.post("/web/usuarios/lote", json={"texto": "Luis Vera; lvera@uti.test; IND\nmal formada\n"}).json()
    assert [c["correo"] for c in lote["creadas"]] == ["lvera@uti.test"] and len(lote["errores"]) == 1

    docente = TestClient(cliente.app)
    entrar(docente, "aperez@uti.test", nueva["clave_temporal"])
    assert docente.get("/web/usuarios").status_code == 403  # un docente no administra cuentas
    assert docente.post("/web/clave", json={"actual": nueva["clave_temporal"], "nueva": "segura-123"}).json()["ok"]

    cliente.patch(f"/web/usuarios/{nueva['id']}", json={"activo": False})
    assert docente.get("/web/yo", headers=WEB).status_code == 401  # la sesión abierta deja de valer
    assert docente.post("/web/login", json={"correo": "aperez@uti.test", "clave": "segura-123"}).status_code == 401


def test_documento_nuevo_y_version_nueva_generan_noticias(cliente, contenedor, tmp_path):
    entrar(cliente, "admin@uti.test", "admin")
    silabo_id = _silabo_terminado(contenedor)

    def subir(ruta, version, fecha):
        with ruta.open("rb") as f:
            r = cliente.post("/documentos", files={"archivo": (ruta.name, f)}, data={
                "titulo": "Lineamientos de evaluación", "tipo": "normativa", "carrera": "TODAS",
                "version": version, "fecha_vigencia": fecha})
        assert r.status_code == 200, r.text
        return r.json()

    v1 = subir(escribir_normativa(tmp_path / "eval_v1.docx", "Primera versión"), "1", "2026-01-01")
    assert v1["noticia"]["titulo"].startswith("Nuevo documento")
    v2 = subir(escribir_normativa(tmp_path / "eval_v2.docx", "Las reentregas ahora son dos."), "2", "2026-06-01")
    noticia = v2["noticia"]
    assert "Nueva versión" in noticia["titulo"] and noticia["categoria"] == "normativa"
    assert "reemplaza a la versión 1" in noticia["resumen"]
    assert any("Secciones del sílabo" in p for p in noticia["puntos"])

    lista = cliente.get("/web/noticias").json()
    assert lista[0]["id"] == noticia["id"]
    assert cliente.get(f"/web/noticias?despues_de={noticia['id']}").json() == []
    # La normativa de prueba se retira: los docentes se enteran y el sílabo lo sabe.
    normativa = next(d for d in cliente.get("/documentos").json() if d["titulo"] == "Normativa de prueba")
    cliente.patch(f"/documentos/{normativa['id']}", json={"estado": "obsoleto"})
    assert "deja de estar vigente" in cliente.get("/web/noticias").json()[0]["titulo"]
    assert silabo_id


def test_pregunta_al_agente_con_rag(cliente):
    entrar(cliente, "docente@uti.test", "docente")
    r = cliente.post("/web/noticias/preguntar", json={"pregunta": "¿Qué niveles tiene la rúbrica socioformativa?"}).json()
    assert r["citas"] and not r["abstencion"]
    assert r["citas"][0]["documento"] == "Normativa de prueba"
    nada = cliente.post("/web/noticias/preguntar", json={"pregunta": "zzqx wwqk"}).json()
    assert nada["abstencion"]


def test_pis_aparte_del_flujo(cliente, contenedor):
    entrar(cliente, "docente@uti.test", "docente")
    asignatura_id, _ = ids(contenedor)
    s = cliente.post("/silabos", json={"asignatura_id": asignatura_id, "periodo": "B26",
                                       "datos_generales": DATOS_GENERALES}).json()
    pis = cliente.get(f"/web/silabos/{s['id']}/pis").json()
    assert pis["estado"] == "vacio" and not all(c["cumple"] for c in pis["criterios"])

    pis = cliente.post(f"/web/silabos/{s['id']}/pis/generar", json={}).json()
    assert pis["estado"] == "propuesto"
    contenido = pis["contenido"]
    assert contenido["problema"] == DATOS_GENERALES["contexto_problema"]
    assert any(f["rap"].startswith("RA1") for f in contenido["articulacion"])
    assert len(contenido["etapas"]) == 5 and contenido["roles"]

    # El docente cambia lo que quiera; el agente rehace solo la parte pedida.
    contenido["titulo"] = "PIS del docente"
    pis = cliente.put(f"/web/silabos/{s['id']}/pis", json={"contenido": contenido}).json()
    assert pis["estado"] == "editado"
    pis = cliente.post(f"/web/silabos/{s['id']}/pis/generar",
                       json={"parte": "proposito", "indicacion": "la ética de los datos"}).json()
    assert pis["contenido"]["titulo"] == "PIS del docente"
    assert "ética de los datos" in pis["contenido"]["proposito"]
    assert [h["origen"] for h in pis["historial"]] == ["agente", "docente", "agente"]
    assert cliente.post(f"/web/silabos/{s['id']}/pis/generar", json={"parte": "inexistente"}).status_code == 400
    # El sílabo recuerda el PIS para la sección 7.2 y el flujo de secciones no se detuvo.
    estado = cliente.get(f"/silabos/{s['id']}").json()
    assert estado["datos_generales"]["pis"]["titulo"] == "PIS del docente"
    assert estado["pausa"]["clave"] == "identificacion"
    # Otra docente no ve ni cambia el PIS ajeno.
    otra = TestClient(cliente.app)
    entrar(otra, "otra@uti.test", "otra")
    assert otra.get(f"/web/silabos/{s['id']}/pis").status_code == 403


def test_documento_final_editable_y_exportacion(cliente, contenedor):
    c = contenedor
    silabo_id = _silabo_terminado(c)
    entrar(cliente, "docente@uti.test", "docente")
    c.pis.generar(silabo_id)

    doc = cliente.get(f"/web/silabos/{silabo_id}/documento").json()
    problema = next(s for s in doc["secciones"] if s["clave"] == "problema_reto")
    assert problema["esquema"]["properties"]
    nuevo = problema["contenido"] | {"pregunta_reto": "¿Cómo podemos reducir el tiempo de elaboración de sílabos?"}
    r = cliente.put(f"/web/silabos/{silabo_id}/documento", json={"secciones": {"problema_reto": nuevo}})
    assert r.status_code == 200, r.text
    assert r.json()["cambiadas"] == ["problema_reto"]
    seccion = next(s for s in c.servicio.estado(silabo_id)["secciones"] if s["clave"] == "problema_reto")
    assert seccion["estado"] == "aprobada" and seccion["origen"] == "docente"
    assert seccion["contenido"]["pregunta_reto"].startswith("¿Cómo podemos reducir")

    # Cambiar un RA oficial se permite en el documento, pero bloquea la versión final.
    ra = next(s for s in doc["secciones"] if s["clave"] == "resultados_aprendizaje")["contenido"]
    oficial = ra["resultados"][0]["enunciado"]
    ra["resultados"][0]["enunciado"] = "Otro enunciado"
    hallazgos = cliente.put(f"/web/silabos/{silabo_id}/documento",
                            json={"secciones": {"resultados_aprendizaje": ra}}).json()["hallazgos"]
    assert any(h["severidad"] == "bloqueante" and not h["resuelto"] for h in hallazgos)
    assert cliente.post(f"/silabos/{silabo_id}/exportar?formato=docx").status_code == 409
    borrador = cliente.post(f"/silabos/{silabo_id}/exportar?formato=docx&borrador=true")
    assert borrador.status_code == 200 and "borrador" in borrador.headers["content-disposition"]

    from docx import Document

    ruta = c.config.exportacion.directorio / f"silabo_ITI-501_B26_{silabo_id}_borrador.docx"
    texto = "\n".join(p.text for p in Document(str(ruta)).paragraphs)
    assert "BORRADOR" in texto and "Observaciones pendientes" in texto
    assert "Proyecto Interdisciplinario Socioformativo" in texto

    # Restituido el RA oficial, la versión final se exporta con el PIS como anexo.
    ra["resultados"][0]["enunciado"] = oficial
    cliente.put(f"/web/silabos/{silabo_id}/documento", json={"secciones": {"resultados_aprendizaje": ra}})
    final = cliente.post(f"/silabos/{silabo_id}/exportar?formato=pdf")
    assert final.status_code == 200, final.text
    assert final.headers["content-type"] == "application/pdf"


def test_la_pagina_se_sirve(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "SyllabusAI" in r.text
    assert cliente.get("/static/app.js").status_code == 200
    assert cliente.get("/web/estado", headers=WEB).status_code == 401
