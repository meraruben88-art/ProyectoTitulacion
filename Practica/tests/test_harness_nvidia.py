import json

import httpx
import pytest
from pydantic import BaseModel

from syllabusai.agent.harness import ErrorHarness, Harness
from syllabusai.config import ConfigEmbeddings, ConfigLLM
from syllabusai.llm.base import RespuestaLLM, SolicitudGeneracion
from syllabusai.llm.openai_compatible import ClienteOpenAICompatible
from syllabusai.retrieval.codificadores import CodificadorNVIDIA


class Salida(BaseModel):
    respuesta: str
    fuentes: list[str] = []


class _Guion:
    """Modelo de prueba que devuelve, en orden, las respuestas de un guion."""

    nombre = "guion"

    def __init__(self, *datos):
        self.datos = list(datos)
        self.mensajes = []

    def generar(self, solicitud: SolicitudGeneracion) -> RespuestaLLM:
        self.mensajes.append(solicitud.mensajes)
        return RespuestaLLM(datos=self.datos.pop(0), texto="", latencia_ms=1.0)


def test_harness_reintenta_con_el_error_y_verifica_citas():
    modelo = _Guion({"sin": "respuesta"}, {"respuesta": "ok", "fuentes": ["f1", "inventada"]})
    r = Harness(modelo).generar("x", [{"role": "user", "content": "hola"}], Salida, fragmentos_validos=["f1", "f2"])
    assert r.intentos == 2 and r.salida.respuesta == "ok"
    assert r.citas_validas == ["f1"] and r.citas_descartadas == ["inventada"]
    # El segundo intento le devolvió al modelo el error de validación.
    assert "no es válida" in modelo.mensajes[1][-1]["content"]


def test_harness_se_rinde_y_cierra_las_herramientas():
    with pytest.raises(ErrorHarness):
        Harness(_Guion({}, {})).generar("x", [], Salida)
    tarea = Harness(_Guion()).tarea("pis", ["consultar_guia_pis"])
    assert tarea.usar("consultar_guia_pis", lambda a: a * 2, 21) == 42
    with pytest.raises(ErrorHarness, match="no tiene permitida"):
        tarea.usar("navegar_internet", print, "x")


def _sse(trozos):
    return "\n\n".join([f"data: {json.dumps(t)}" for t in trozos] + ["data: [DONE]"]).encode()


def test_cliente_nvidia_build(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-prueba")
    recibido = {}

    def manejador(peticion: httpx.Request) -> httpx.Response:
        recibido["auth"] = peticion.headers["authorization"]
        recibido["cuerpo"] = json.loads(peticion.content)
        return httpx.Response(200, content=_sse([
            # Los modelos de razonamiento envían su traza aparte: no cuenta como respuesta.
            {"choices": [{"delta": {"reasoning_content": "pienso…"}}]},
            {"choices": [{"delta": {"content": '{"respuesta": "hola"}'}}]},
            {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 3}},
        ]), headers={"content-type": "text/event-stream"})

    config = ConfigLLM(proveedor="nvidia", url="https://integrate.api.nvidia.com/v1",
                       modelo="nvidia/nemotron-3-super-120b-a12b", salida_estructurada="guided_json",
                       extra={"chat_template_kwargs": {"enable_thinking": False}})
    cliente = ClienteOpenAICompatible(config, transporte=httpx.MockTransport(manejador))
    r = cliente.generar(SolicitudGeneracion("x", [{"role": "user", "content": "hola"}], {"type": "object"}))
    assert r.datos == {"respuesta": "hola"} and r.tokens_out == 3
    assert recibido["auth"] == "Bearer nvapi-prueba"
    cuerpo = recibido["cuerpo"]
    assert cuerpo["model"] == "nvidia/nemotron-3-super-120b-a12b"
    assert cuerpo["nvext"] == {"guided_json": {"type": "object"}} and "response_format" not in cuerpo
    assert cuerpo["chat_template_kwargs"] == {"enable_thinking": False}


def test_embeddings_nvidia(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-prueba")

    def manejador(peticion: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(peticion.content)
        assert cuerpo["model"] == "baai/bge-m3"
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [3.0, 4.0]} for i, _ in enumerate(cuerpo["input"])]})

    cod = CodificadorNVIDIA(ConfigEmbeddings(proveedor="nvidia", modelo="baai/bge-m3", dimension=2),
                            transporte=httpx.MockTransport(manejador))
    assert cod.codificar(["a", "b"]) == [[0.6, 0.8], [0.6, 0.8]]
