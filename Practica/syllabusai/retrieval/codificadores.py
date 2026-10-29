"""Modelos de embeddings densos intercambiables (D-5).

En el servidor con la A100 se usa BGE-M3 mediante sentence-transformers (extra `embeddings`).
Sin GPU el prototipo funciona solo con la señal léxica; el codificador «hash» existe para
ejercitar la ruta densa en las pruebas sin descargar modelos.
"""

import hashlib
import math
from typing import Protocol

from syllabusai.config import ConfigEmbeddings
from syllabusai.retrieval.lexico import tokenizar


class CodificadorDenso(Protocol):
    nombre: str
    dimension: int

    def codificar(self, textos: list[str]) -> list[list[float]]: ...


class CodificadorHash:
    """Vectores deterministas por hashing de términos. No captura sinonimia: solo pruebas."""

    def __init__(self, dimension: int = 256):
        self.nombre = f"hash-{dimension}"
        self.dimension = dimension

    def codificar(self, textos: list[str]) -> list[list[float]]:
        vectores = []
        for texto in textos:
            vector = [0.0] * self.dimension
            for token in tokenizar(texto):
                h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
                vector[h % self.dimension] += 1.0 if (h >> 32) & 1 else -1.0
            norma = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectores.append([v / norma for v in vector])
        return vectores


class CodificadorSentenceTransformers:
    def __init__(self, modelo: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "Falta el extra de embeddings: pip install -e .[embeddings]"
            ) from error
        self._modelo = SentenceTransformer(modelo)
        self.nombre = modelo
        self.dimension = self._modelo.get_sentence_embedding_dimension()

    def codificar(self, textos: list[str]) -> list[list[float]]:
        return self._modelo.encode(textos, normalize_embeddings=True, batch_size=16).tolist()


def crear_codificador(config: ConfigEmbeddings) -> CodificadorDenso | None:
    if config.proveedor == "ninguno":
        return None
    if config.proveedor == "hash":
        return CodificadorHash(config.dimension)
    return CodificadorSentenceTransformers(config.modelo)
