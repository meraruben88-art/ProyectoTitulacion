"""Base vectorial Qdrant: fragmentos, metadatos y búsqueda filtrada (RF-05, RF-10, RF-11).

Cada punto guarda dos vectores con nombre: «lexica» (disperso, BM25 con IDF de Qdrant) y,
si hay modelo de embeddings, «densa». La carga útil es `PayloadFragmento`, de modo que la
búsqueda puede restringirse por tipo de documento, carrera y vigencia antes de puntuar.
"""

import uuid

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from syllabusai.config import ConfigBaseVectorial
from syllabusai.db.modelos import TipoDocumento
from syllabusai.esquemas import PayloadFragmento

# Documentos que rigen para toda la universidad (Modelo Educativo, formato de sílabo, guías).
CARRERA_INSTITUCIONAL = "TODAS"


class ErrorAlmacen(RuntimeError):
    pass


def id_punto(fragmento_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"syllabusai/{fragmento_id}"))


def filtro(
    tipos: list[TipoDocumento] | None = None,
    carrera: str | None = None,
    solo_vigentes: bool = True,
) -> qm.Filter | None:
    condiciones = []
    if solo_vigentes:
        condiciones.append(qm.FieldCondition(key="vigente", match=qm.MatchValue(value=True)))
    if tipos:
        condiciones.append(qm.FieldCondition(
            key="tipo_documento", match=qm.MatchAny(any=[str(t) for t in tipos])
        ))
    if carrera:
        condiciones.append(qm.FieldCondition(
            key="carrera", match=qm.MatchAny(any=[carrera, CARRERA_INSTITUCIONAL])
        ))
    return qm.Filter(must=condiciones) if condiciones else None


class AlmacenVectorial:
    def __init__(self, cliente: QdrantClient, coleccion: str, dimension_densa: int | None):
        self.cliente = cliente
        self.coleccion = coleccion
        self.dimension_densa = dimension_densa
        self._asegurar_coleccion()

    @classmethod
    def abrir(cls, config: ConfigBaseVectorial, dimension_densa: int | None) -> "AlmacenVectorial":
        if config.url:
            cliente = QdrantClient(url=config.url)
        elif config.ruta:
            config.ruta.mkdir(parents=True, exist_ok=True)
            cliente = QdrantClient(path=str(config.ruta))
        else:
            cliente = QdrantClient(":memory:")
        return cls(cliente, config.coleccion, dimension_densa)

    def _asegurar_coleccion(self) -> None:
        if self.cliente.collection_exists(self.coleccion):
            vectores = self.cliente.get_collection(self.coleccion).config.params.vectors or {}
            densa = vectores.get("densa") if isinstance(vectores, dict) else None
            dimension = densa.size if densa else None
            if dimension != self.dimension_densa:
                raise ErrorAlmacen(
                    f"La colección «{self.coleccion}» se indexó con dimensión densa {dimension} y "
                    f"la configuración pide {self.dimension_densa}. Reindexe el corpus con "
                    "`syllabusai ingestar --reindexar` tras borrar la base vectorial."
                )
            return
        vectores = {}
        if self.dimension_densa:
            vectores["densa"] = qm.VectorParams(size=self.dimension_densa, distance=qm.Distance.COSINE)
        self.cliente.create_collection(
            self.coleccion,
            vectors_config=vectores,
            sparse_vectors_config={"lexica": qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
        )

    def indexar(
        self,
        fragmentos: list[PayloadFragmento],
        lexicos: list[tuple[list[int], list[float]]],
        densos: list[list[float]] | None,
    ) -> None:
        puntos = []
        for i, fragmento in enumerate(fragmentos):
            indices, valores = lexicos[i]
            vector = {"lexica": qm.SparseVector(indices=indices, values=valores)}
            if densos is not None:
                vector["densa"] = densos[i]
            puntos.append(qm.PointStruct(
                id=id_punto(fragmento.fragmento_id), vector=vector,
                payload=fragmento.model_dump(mode="json"),
            ))
        for inicio in range(0, len(puntos), 128):
            self.cliente.upsert(self.coleccion, puntos[inicio:inicio + 128])

    def _filtro_documento(self, documento_id: int) -> qm.Filter:
        return qm.Filter(must=[
            qm.FieldCondition(key="documento_id", match=qm.MatchValue(value=documento_id))
        ])

    def eliminar_documento(self, documento_id: int) -> None:
        self.cliente.delete(
            self.coleccion, points_selector=qm.FilterSelector(filter=self._filtro_documento(documento_id))
        )

    def marcar_vigencia(self, documento_id: int, vigente: bool) -> None:
        self.cliente.set_payload(
            self.coleccion, payload={"vigente": vigente}, points=self._filtro_documento(documento_id)
        )

    def contar(self, documento_id: int | None = None) -> int:
        f = self._filtro_documento(documento_id) if documento_id is not None else None
        return self.cliente.count(self.coleccion, count_filter=f, exact=True).count

    def obtener(self, fragmento_ids: list[str]) -> dict[str, PayloadFragmento]:
        if not fragmento_ids:
            return {}
        puntos = self.cliente.retrieve(self.coleccion, ids=[id_punto(f) for f in fragmento_ids])
        return {p.payload["fragmento_id"]: PayloadFragmento.model_validate(p.payload) for p in puntos}

    def todos(self) -> list[PayloadFragmento]:
        """Todos los fragmentos indexados (para la evaluación del recuperador)."""
        fragmentos, desde = [], None
        while True:
            puntos, desde = self.cliente.scroll(self.coleccion, limit=256, offset=desde,
                                                with_payload=True, with_vectors=False)
            fragmentos += [PayloadFragmento.model_validate(p.payload) for p in puntos]
            if desde is None:
                return fragmentos

    def buscar_lexica(self, indices, valores, condicion, limite) -> list[qm.ScoredPoint]:
        if not indices:
            return []
        return self.cliente.query_points(
            self.coleccion, query=qm.SparseVector(indices=indices, values=valores),
            using="lexica", query_filter=condicion, limit=limite,
        ).points

    def buscar_hibrida(self, densa, indices, valores, condicion, candidatos, limite):
        prefetch = [qm.Prefetch(query=densa, using="densa", limit=candidatos, filter=condicion)]
        if indices:
            prefetch.append(qm.Prefetch(
                query=qm.SparseVector(indices=indices, values=valores), using="lexica",
                limit=candidatos, filter=condicion,
            ))
        return self.cliente.query_points(
            self.coleccion, prefetch=prefetch, query=qm.FusionQuery(fusion=qm.Fusion.RRF),
            limit=limite,
        ).points

    def cerrar(self) -> None:
        self.cliente.close()
