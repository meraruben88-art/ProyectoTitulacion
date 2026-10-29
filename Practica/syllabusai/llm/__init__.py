"""Clientes de modelo de lenguaje: vLLM (compatible con OpenAI) y simulado."""

from syllabusai.config import ConfigLLM
from syllabusai.llm.base import ClienteLLM


def crear_cliente(config: ConfigLLM) -> ClienteLLM:
    if config.proveedor == "openai":
        from syllabusai.llm.openai_compatible import ClienteOpenAICompatible

        return ClienteOpenAICompatible(config)
    from syllabusai.llm.simulado import ClienteSimulado

    return ClienteSimulado(retardo_token_s=config.retardo_simulado_ms / 1000)
