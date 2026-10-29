import json

import httpx
import pytest

from syllabusai.config import ConfigLLM
from syllabusai.llm.base import ErrorLLM, SolicitudGeneracion, extraer_json
from syllabusai.llm.openai_compatible import ClienteOpenAICompatible


def test_extrae_json_con_razonamiento_y_bloque_de_codigo():
    texto = '<think>pienso...</think>\n```json\n{"contenido": {"a": 1}, "fuentes": []}\n```'
    assert extraer_json(texto) == {"contenido": {"a": 1}, "fuentes": []}
    with pytest.raises(ErrorLLM):
        extraer_json("sin json")


def _sse(trozos):
    lineas = [f"data: {json.dumps(t)}" for t in trozos] + ["data: [DONE]"]
    return "\n\n".join(lineas).encode()


def test_cliente_vllm_hace_streaming_y_mide_ttft():
    recibido = {}

    def manejador(peticion: httpx.Request) -> httpx.Response:
        recibido.update(json.loads(peticion.content))
        cuerpo = _sse([
            {"choices": [{"delta": {"content": '{"contenido": '}}]},
            {"choices": [{"delta": {"content": '{"x": 1}, "fuentes": ["d1-f0001"]}'}}]},
            {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 18}},
        ])
        return httpx.Response(200, content=cuerpo, headers={"content-type": "text/event-stream"})

    cliente = ClienteOpenAICompatible(ConfigLLM(proveedor="openai"), transporte=httpx.MockTransport(manejador))
    respuesta = cliente.generar(SolicitudGeneracion("contenidos", [{"role": "user", "content": "hola"}],
                                                    {"type": "object"}))
    assert respuesta.datos == {"contenido": {"x": 1}, "fuentes": ["d1-f0001"]}
    assert respuesta.tokens_in == 120 and respuesta.tokens_out == 18
    assert respuesta.ttft_ms is not None and respuesta.ttft_ms <= respuesta.latencia_ms
    assert recibido["stream"] is True and recibido["model"] == "Qwen/Qwen3-8B"
    assert recibido["response_format"]["type"] == "json_schema"
    assert recibido["chat_template_kwargs"] == {"enable_thinking": False}


def test_cliente_vllm_informa_errores_del_servidor():
    cliente = ClienteOpenAICompatible(
        ConfigLLM(proveedor="openai"),
        transporte=httpx.MockTransport(lambda r: httpx.Response(503, text="sin GPU")),
    )
    with pytest.raises(ErrorLLM, match="503"):
        cliente.generar(SolicitudGeneracion("x", [], {}))
