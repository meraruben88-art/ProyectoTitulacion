import pytest
from conftest import DATOS_GENERALES, ids
from fastapi.testclient import TestClient

from syllabusai.api.app import crear_app

DOCENTE = ("docente@uti.test", "docente")
ADMIN = ("admin@uti.test", "admin")


@pytest.fixture
def cliente(contenedor):
    return TestClient(crear_app(lambda: contenedor))


def test_autenticacion_basica(cliente):
    assert cliente.post("/auth/login", auth=("docente@uti.test", "mala")).status_code == 401
    assert cliente.post("/auth/login", auth=DOCENTE).json()["rol"] == "docente"


def test_flujo_por_api(cliente, contenedor):
    asignatura_id, _ = ids(contenedor)
    r = cliente.post("/silabos", auth=DOCENTE, json={
        "asignatura_id": asignatura_id, "periodo": "B26", "datos_generales": DATOS_GENERALES,
    })
    assert r.status_code == 200, r.text
    silabo = r.json()
    sid = silabo["id"]
    assert silabo["pausa"]["clave"] == "identificacion"

    # Solo se actúa sobre la sección que el flujo espera.
    r = cliente.post(f"/silabos/{sid}/secciones/evaluacion/aprobar", auth=DOCENTE, json={})
    assert r.status_code == 409
    # Otra docente no puede ver ni modificar el sílabo.
    assert cliente.get(f"/silabos/{sid}", auth=("otra@uti.test", "otra")).status_code == 403
    # Exportar antes de aprobar todo está prohibido (RF-42).
    assert cliente.post(f"/silabos/{sid}/exportar", auth=DOCENTE).status_code == 409

    while silabo["pausa"]["tipo"] == "revision_seccion":
        clave = silabo["pausa"]["clave"]
        silabo = cliente.post(f"/silabos/{sid}/secciones/{clave}/aprobar", auth=DOCENTE, json={}).json()
    assert silabo["pausa"]["tipo"] == "terminado" and silabo["estado"] == "aprobado"

    r = cliente.post(f"/silabos/{sid}/exportar?formato=pdf", auth=DOCENTE)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert cliente.get("/silabos", auth=DOCENTE).json()[0]["estado"] == "exportado"


def test_corpus_solo_para_administrador(cliente, tmp_path):
    from conftest import escribir_normativa

    ruta = escribir_normativa(tmp_path / "nueva.docx", nota="Versión 2 con cambios.")
    datos = {"titulo": "Normativa de prueba", "tipo": "normativa", "carrera": "TODAS",
             "version": "2", "fecha_vigencia": "2026-09-01"}
    with ruta.open("rb") as archivo:
        r = cliente.post("/documentos", auth=DOCENTE, data=datos, files={"archivo": archivo})
    assert r.status_code == 403
    # Una versión nueva deja obsoleta a la anterior sin borrarla (RF-06).
    with ruta.open("rb") as archivo:
        r = cliente.post("/documentos", auth=ADMIN, data=datos, files={"archivo": archivo})
    assert r.status_code == 200 and r.json()["estado"] == "vigente" and r.json()["fragmentos"] > 0
    versiones = [d for d in cliente.get("/documentos", auth=ADMIN).json() if d["titulo"] == datos["titulo"]]
    assert sorted((d["version"], d["estado"]) for d in versiones) == [("1", "obsoleto"), ("2", "vigente")]
    # El mismo archivo no se registra dos veces.
    with ruta.open("rb") as archivo:
        r = cliente.post("/documentos", auth=ADMIN, data=datos | {"version": "3"}, files={"archivo": archivo})
    assert r.status_code == 400 and "ya está en el corpus" in r.json()["detail"]

    documentos = cliente.get("/documentos", auth=ADMIN).json()
    assert all(d["fragmentos"] > 0 for d in documentos)
    perfil = next(d for d in documentos if d["tipo"] == "perfil_egreso")
    r = cliente.patch(f"/documentos/{perfil['id']}", auth=ADMIN, json={"estado": "obsoleto"})
    assert r.json()["estado"] == "obsoleto"
    r = cliente.post("/buscar", auth=DOCENTE, json={"consulta": "PE-PP-04", "tipos": ["perfil_egreso"]})
    assert r.json() == []


def test_decision_en_vivo_transmite_pasos_y_texto(cliente, contenedor):
    import json

    asignatura_id, _ = ids(contenedor)
    sid = cliente.post("/silabos", auth=DOCENTE, json={
        "asignatura_id": asignatura_id, "periodo": "B26", "datos_generales": DATOS_GENERALES,
    }).json()["id"]
    with cliente.stream("POST", f"/silabos/{sid}/secciones/identificacion/stream", auth=DOCENTE,
                        json={"accion": "aprobar"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        eventos = [json.loads(linea[5:]) for linea in r.iter_lines() if linea.startswith("data:")]
    tipos = [e["tipo"] for e in eventos]
    assert "paso" in tipos and "token" in tipos and tipos[-1] == "fin"
    assert eventos[-1]["silabo"]["pausa"]["clave"] == "anclaje_curricular"
    # El texto transmitido es la propuesta que quedó guardada.
    texto = "".join(e["texto"] for e in eventos if e["tipo"] == "token")
    assert json.loads(texto)["contenido"]["competencia_especifica"]


def test_preferencias_se_ven_y_se_editan(cliente, contenedor):
    asignatura_id, _ = ids(contenedor)
    datos = DATOS_GENERALES | {"indicaciones_generales": "trabajo individual y usa Python"}
    silabo = cliente.post("/silabos", auth=DOCENTE, json={
        "asignatura_id": asignatura_id, "periodo": "B26", "datos_generales": datos}).json()
    assert "modalidad de trabajo: individual" in silabo["preferencias"]
    preferencias = silabo["datos_generales"]["preferencias"] | {"politica_ia": "prohibida"}
    r = cliente.put(f"/silabos/{silabo['id']}/preferencias", auth=DOCENTE, json=preferencias)
    assert "política de uso de IA: prohibida" in r.json()["preferencias"]
    r = cliente.put(f"/silabos/{silabo['id']}/preferencias", auth=DOCENTE,
                    json={"politica_ia": "a veces"})
    assert r.status_code == 422
