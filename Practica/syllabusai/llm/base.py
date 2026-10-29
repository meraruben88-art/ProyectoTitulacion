"""Contrato común de los clientes de modelo de lenguaje."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SolicitudGeneracion:
    clave: str  # sección del sílabo que se genera
    mensajes: list[dict[str, str]]  # instrucciones para un modelo real (system + user)
    esquema: dict[str, Any]  # JSON Schema de la salida esperada
    # Datos estructurados de la misma solicitud; el modelo simulado trabaja sobre ellos.
    contexto: dict[str, Any] = field(default_factory=dict)
    # Recibe cada trozo de texto a medida que el modelo lo produce (streaming, RNF-07).
    al_token: Callable[[str], None] | None = None


@dataclass
class RespuestaLLM:
    datos: dict[str, Any]
    texto: str
    latencia_ms: float
    ttft_ms: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    modelo: str = ""


class ErrorLLM(RuntimeError):
    """El modelo no respondió o su respuesta no es JSON válido."""


class ClienteLLM(Protocol):
    nombre: str

    def generar(self, solicitud: SolicitudGeneracion) -> RespuestaLLM: ...


_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.DOTALL)
_BLOQUE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extraer_json(texto: str) -> dict[str, Any]:
    """Obtiene el objeto JSON de la respuesta aunque venga con razonamiento o entre ```."""
    limpio = _PENSAMIENTO.sub("", texto).strip()
    bloque = _BLOQUE.search(limpio)
    if bloque:
        limpio = bloque.group(1).strip()
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ErrorLLM("La respuesta no contiene un objeto JSON")
    try:
        datos = json.loads(limpio[inicio:fin + 1])
    except json.JSONDecodeError as error:
        raise ErrorLLM(f"JSON inválido en la respuesta: {error}") from error
    if not isinstance(datos, dict):
        raise ErrorLLM("La respuesta JSON no es un objeto")
    return datos
