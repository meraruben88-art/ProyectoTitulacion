"""Cliente para servidores compatibles con la API de OpenAI.

Sirve para los tres despliegues del modelo: vLLM propio, NVIDIA Build (API alojada en
`integrate.api.nvidia.com`) y un NIM levantado en una instancia de NVIDIA Brev. Los tres reciben
la misma petición `/chat/completions`; cambian la URL, la clave y la forma de pedir la salida
estructurada.

La respuesta se pide en streaming para medir el tiempo hasta el primer token (RF-50). Los
modelos de razonamiento (Nemotron 3 Super, gpt-oss) envían su razonamiento en
`reasoning_content`: no forma parte de la respuesta ni del TTFT, que se mide sobre el contenido.
"""

import json
import time

import httpx

from syllabusai.config import ConfigLLM, clave_api
from syllabusai.llm.base import ErrorLLM, RespuestaLLM, SolicitudGeneracion, extraer_json

URL_NVIDIA_BUILD = "https://integrate.api.nvidia.com/v1"


class ClienteOpenAICompatible:
    def __init__(self, config: ConfigLLM, transporte: httpx.BaseTransport | None = None):
        self.config = config
        self.nombre = config.modelo
        variable = config.api_key_env or ("NVIDIA_API_KEY" if config.proveedor == "nvidia" else None)
        clave = clave_api(config.api_key, variable)
        self._http = httpx.Client(
            base_url=config.url.rstrip("/"),
            headers={"Authorization": f"Bearer {clave}"},
            timeout=httpx.Timeout(config.timeout_s, connect=10.0),
            transport=transporte,
        )

    def _cuerpo(self, solicitud: SolicitudGeneracion) -> dict:
        cuerpo = {
            "model": self.config.modelo,
            "messages": solicitud.mensajes,
            "temperature": self.config.temperatura,
            "max_tokens": self.config.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        nombre = f"salida_{solicitud.clave}"
        modo = self.config.salida_estructurada
        if modo == "json_schema":
            cuerpo["response_format"] = {
                "type": "json_schema", "json_schema": {"name": nombre, "schema": solicitud.esquema},
            }
        elif modo == "guided_json":
            cuerpo["nvext"] = {"guided_json": solicitud.esquema}
        elif modo == "json_object":
            cuerpo["response_format"] = {"type": "json_object"}
        if self.config.proveedor == "openai":
            # Parámetro de vLLM para la plantilla de chat de Qwen3 (modo con o sin razonamiento).
            cuerpo["chat_template_kwargs"] = {"enable_thinking": self.config.pensar}
        return cuerpo | self.config.extra

    def generar(self, solicitud: SolicitudGeneracion) -> RespuestaLLM:
        inicio = time.perf_counter()
        ttft = None
        partes: list[str] = []
        uso: dict = {}
        try:
            with self._http.stream("POST", "/chat/completions", json=self._cuerpo(solicitud)) as r:
                if r.status_code >= 400:
                    r.read()
                    raise ErrorLLM(f"El servidor respondió {r.status_code}: {r.text[:300]}")
                for linea in r.iter_lines():
                    if not linea.startswith("data:"):
                        continue
                    dato = linea[5:].strip()
                    if dato == "[DONE]":
                        break
                    trozo = json.loads(dato)
                    uso = trozo.get("usage") or uso
                    for opcion in trozo.get("choices", []):
                        contenido = (opcion.get("delta") or {}).get("content")
                        if contenido:
                            if ttft is None:
                                ttft = (time.perf_counter() - inicio) * 1000
                            partes.append(contenido)
                            if solicitud.al_token is not None:
                                solicitud.al_token(contenido)
        except httpx.HTTPError as error:
            raise ErrorLLM(f"No se pudo contactar al modelo en {self.config.url}: {error}") from error

        texto = "".join(partes)
        return RespuestaLLM(
            datos=extraer_json(texto),
            texto=texto,
            latencia_ms=(time.perf_counter() - inicio) * 1000,
            ttft_ms=ttft,
            tokens_in=uso.get("prompt_tokens"),
            tokens_out=uso.get("completion_tokens"),
            modelo=self.config.modelo,
        )
