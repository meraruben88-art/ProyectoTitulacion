"""Modelos de embeddings densos intercambiables (D-5).

BGE-M3 puede correr localmente con sentence-transformers (extra `embeddings`) o pedirse a la API
de embeddings de NVIDIA (NVIDIA Build o un NIM en NVIDIA Brev). Sin modelo el prototipo funciona
solo con la señal léxica; el codificador «hash» existe para ejercitar la ruta densa en las
pruebas sin descargar modelos.
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


class CodificadorNVIDIA:
    """Embeddings por la API de NVIDIA (`/v1/embeddings`, compatible con OpenAI)."""

    def __init__(self, config: ConfigEmbeddings, transporte=None):
        import httpx

        from syllabusai.config import clave_api

        self.nombre = config.modelo
        self.dimension = config.dimension
        self.tipo_entrada = config.tipo_entrada
        self._http = httpx.Client(
            base_url=config.url.rstrip("/"), timeout=60.0, transport=transporte,
            headers={"Authorization": f"Bearer {clave_api('', config.api_key_env)}"},
        )

    def codificar(self, textos: list[str]) -> list[list[float]]:
        vectores: list[list[float]] = []
        for i in range(0, len(textos), 32):
            cuerpo = {"model": self.nombre, "input": textos[i:i + 32], "encoding_format": "float",
                      "truncate": "END"}
            if self.tipo_entrada:
                cuerpo["input_type"] = self.tipo_entrada
            r = self._http.post("/embeddings", json=cuerpo)
            if r.status_code >= 400:
                raise RuntimeError(f"La API de embeddings respondió {r.status_code}: {r.text[:300]}")
            datos = sorted(r.json()["data"], key=lambda d: d["index"])
            for d in datos:
                norma = math.sqrt(sum(v * v for v in d["embedding"])) or 1.0
                vectores.append([v / norma for v in d["embedding"]])
        return vectores


def crear_codificador(config: ConfigEmbeddings) -> CodificadorDenso | None:
    if config.proveedor == "ninguno":
        return None
    if config.proveedor == "hash":
        return CodificadorHash(config.dimension)
    if config.proveedor == "nvidia":
        return CodificadorNVIDIA(config)
    return CodificadorSentenceTransformers(config.modelo)
