"""Harness del agente: el entorno controlado en que trabaja el modelo de lenguaje.

El modelo (Nemotron 3 Super 120B en NVIDIA Build o en un NIM de NVIDIA Brev, o el simulado) no
actúa por su cuenta: el harness decide qué puede usar y qué se acepta de lo que devuelve.

- **Herramientas cerradas.** Cada tarea declara su lista de herramientas; pedir una que no está
  en la lista es un error, no una llamada (RF-22).
- **Salida estructurada y validada.** La respuesta debe cumplir el esquema Pydantic de la tarea.
  Si no lo cumple, se le devuelve al modelo el error de validación y se reintenta.
- **Citas verificadas.** Solo valen los identificadores de los fragmentos que se le entregaron;
  los demás se descartan y quedan anotados (RF-13).
- **Telemetría.** Cada llamada deja latencia, TTFT, tokens, intentos y herramientas usadas.

Lo usan las secciones del sílabo (`servicio.py`), el PIS (`pis/`) y las noticias (`noticias/`).
"""

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from syllabusai.llm.base import ClienteLLM, ErrorLLM, RespuestaLLM, SolicitudGeneracion


class ErrorHarness(ValueError):
    """El modelo no produjo una salida válida o se pidió algo fuera de lo permitido."""


@dataclass
class Resultado:
    salida: BaseModel
    respuesta: RespuestaLLM
    intentos: int
    citas_validas: list[str] = field(default_factory=list)
    citas_descartadas: list[str] = field(default_factory=list)
    herramientas: list[str] = field(default_factory=list)

    def metricas(self) -> dict[str, Any]:
        r = self.respuesta
        return {"latencia_ms": r.latencia_ms, "ttft_ms": r.ttft_ms, "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out, "modelo": r.modelo, "intentos": self.intentos,
                "herramientas": self.herramientas}


class Tarea:
    """Una tarea del agente con su conjunto cerrado de herramientas."""

    def __init__(self, harness: "Harness", nombre: str, permitidas: Iterable[str]):
        self.harness = harness
        self.nombre = nombre
        self.permitidas = frozenset(permitidas)
        self.usadas: list[str] = []

    def usar(self, herramienta: str, funcion: Callable[..., Any], *args, **kwargs) -> Any:
        if herramienta not in self.permitidas:
            raise ErrorHarness(
                f"La tarea «{self.nombre}» no tiene permitida la herramienta «{herramienta}»"
            )
        self.usadas.append(herramienta)
        return funcion(*args, **kwargs)

    def generar(self, mensajes: list[dict[str, str]], modelo_salida: type[BaseModel], **kwargs) -> Resultado:
        resultado = self.harness.generar(self.nombre, mensajes, modelo_salida, **kwargs)
        resultado.herramientas = list(dict.fromkeys(self.usadas))
        return resultado


class Harness:
    def __init__(self, llm: ClienteLLM, reintentos: int = 1):
        self.llm = llm
        self.reintentos = reintentos

    def tarea(self, nombre: str, permitidas: Iterable[str] = ()) -> Tarea:
        return Tarea(self, nombre, permitidas)

    def generar(
        self,
        clave: str,
        mensajes: list[dict[str, str]],
        modelo_salida: type[BaseModel],
        contexto: dict[str, Any] | None = None,
        al_token: Callable[[str], None] | None = None,
        fragmentos_validos: Iterable[str] | None = None,
        campo_fuentes: str = "fuentes",
    ) -> Resultado:
        """Llama al modelo hasta obtener una salida que cumpla el esquema."""
        ultimo_error: Exception | None = None
        inicio = time.perf_counter()
        for intento in range(1, self.reintentos + 2):
            solicitud = SolicitudGeneracion(
                clave=clave, mensajes=mensajes, esquema=modelo_salida.model_json_schema(),
                contexto=contexto or {}, al_token=al_token,
            )
            try:
                respuesta = self.llm.generar(solicitud)
                salida = modelo_salida.model_validate(respuesta.datos)
            except (ErrorLLM, ValidationError) as error:
                ultimo_error = error
                # La retroalimentación del validador vuelve al modelo como un turno más.
                mensajes = mensajes + [{"role": "user", "content": (
                    f"Tu respuesta anterior no es válida: {str(error)[:800]}. Devuelve solo el "
                    "objeto JSON corregido."
                )}]
                continue
            respuesta.latencia_ms = (time.perf_counter() - inicio) * 1000
            validas, descartadas = self._verificar_citas(salida, fragmentos_validos, campo_fuentes)
            return Resultado(salida, respuesta, intento, validas, descartadas)
        raise ErrorHarness(f"El modelo no produjo una respuesta válida: {ultimo_error}")

    @staticmethod
    def _verificar_citas(
        salida: BaseModel, fragmentos_validos: Iterable[str] | None, campo: str
    ) -> tuple[list[str], list[str]]:
        citadas = list(dict.fromkeys(getattr(salida, campo, None) or []))
        if fragmentos_validos is None:
            return citadas, []
        permitidos = set(fragmentos_validos)
        return ([c for c in citadas if c in permitidos], [c for c in citadas if c not in permitidos])
