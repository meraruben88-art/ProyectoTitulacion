"""Clientes de modelo de lenguaje: compatibles con OpenAI (vLLM, NVIDIA Build, NIM en Brev) y
simulado."""

from syllabusai.config import ConfigLLM
from syllabusai.llm.base import ClienteLLM


def crear_cliente(config: ConfigLLM) -> ClienteLLM:
    if config.proveedor in ("openai", "nvidia"):
        from syllabusai.llm.openai_compatible import ClienteOpenAICompatible

        return ClienteOpenAICompatible(config)
    from syllabusai.llm.simulado import ClienteSimulado

    return ClienteSimulado(retardo_token_s=config.retardo_simulado_ms / 1000)
