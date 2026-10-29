"""Cliente para servidores compatibles con la API de OpenAI (vLLM sirviendo Qwen3-8B en la A100).

La respuesta se pide en streaming para medir el tiempo hasta el primer token (RF-50), y con
`response_format` de tipo JSON Schema para que vLLM restrinja la decodificación al esquema de
la sección.
"""

import json
import time

import httpx

from syllabusai.config import ConfigLLM
from syllabusai.llm.base import ErrorLLM, RespuestaLLM, SolicitudGeneracion, extraer_json


class ClienteOpenAICompatible:
    def __init__(self, config: ConfigLLM, transporte: httpx.BaseTransport | None = None):
        self.config = config
        self.nombre = config.modelo
        self._http = httpx.Client(
            base_url=config.url.rstrip("/"),
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(config.timeout_s, connect=10.0),
            transport=transporte,
        )

    def _cuerpo(self, solicitud: SolicitudGeneracion) -> dict:
        return {
            "model": self.config.modelo,
            "messages": solicitud.mensajes,
            "temperature": self.config.temperatura,
            "max_tokens": self.config.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": f"seccion_{solicitud.clave}", "schema": solicitud.esquema},
            },
            # Parámetro de vLLM para la plantilla de chat de Qwen3 (modo con o sin razonamiento).
            "chat_template_kwargs": {"enable_thinking": self.config.pensar},
        }

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
