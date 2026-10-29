"""Recuperación híbrida con filtros y registro de cada consulta (RF-10 a RF-12, RF-15)."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from syllabusai.config import ConfigRecuperacion
from syllabusai.db.modelos import TipoDocumento
from syllabusai.esquemas import PayloadFragmento
from syllabusai.retrieval.almacen import AlmacenVectorial, filtro
from syllabusai.retrieval.codificadores import CodificadorDenso
from syllabusai.retrieval.lexico import vector_consulta, vector_documento


@dataclass
class FragmentoRecuperado:
    fragmento: PayloadFragmento
    puntaje: float
    # Puntaje BM25 del fragmento para la consulta; 0 si no comparte ningún término con ella.
    # Es la señal que decide la abstención, porque el puntaje RRF no es comparable entre consultas.
    puntaje_lexico: float

    @property
    def cita(self) -> str:
        f = self.fragmento
        paginas = f"p. {f.pagina_inicio}" + (f"–{f.pagina_fin}" if f.pagina_fin != f.pagina_inicio else "")
        return f"{f.titulo}, versión {f.version}, {paginas}"


# Recibe (consulta, filtros, resultados, latencia_ms) para registrarlo como evento.
Registro = Callable[[str, dict, list[FragmentoRecuperado], float], None]


class Recuperador:
    def __init__(
        self,
        almacen: AlmacenVectorial,
        codificador: CodificadorDenso | None,
        config: ConfigRecuperacion,
        registro: Registro | None = None,
    ):
        self.almacen = almacen
        self.codificador = codificador
        self.config = config
        self.registro = registro

    def texto_indexable(self, fragmento: PayloadFragmento) -> str:
        """Título del documento y ruta de sección forman parte del texto que se puntúa."""
        return "\n".join([fragmento.titulo, " > ".join(fragmento.ruta_seccion), fragmento.texto])

    def indexar(self, fragmentos: list[PayloadFragmento]) -> None:
        textos = [self.texto_indexable(f) for f in fragmentos]
        c = self.config
        lexicos = [vector_documento(t, c.bm25_k1, c.bm25_b, c.bm25_longitud_media) for t in textos]
        densos = self.codificador.codificar(textos) if self.codificador else None
        self.almacen.indexar(fragmentos, lexicos, densos)

    def buscar(
        self,
        consulta: str,
        tipos: list[TipoDocumento] | None = None,
        carrera: str | None = None,
        solo_vigentes: bool = True,
        k: int | None = None,
        registro: Registro | None = None,
    ) -> list[FragmentoRecuperado]:
        inicio = time.perf_counter()
        k = k or self.config.top_k
        condicion = filtro(tipos, carrera, solo_vigentes)
        indices, valores = vector_consulta(consulta)
        lexicos = self.almacen.buscar_lexica(indices, valores, condicion, self.config.candidatos)
        puntaje_lexico = {p.id: p.score for p in lexicos}

        if self.codificador is not None:
            densa = self.codificador.codificar([consulta])[0]
            puntos = self.almacen.buscar_hibrida(
                densa, indices, valores, condicion, self.config.candidatos, k
            )
        else:
            puntos = lexicos[:k]

        resultados = [
            FragmentoRecuperado(
                PayloadFragmento.model_validate(p.payload), p.score, puntaje_lexico.get(p.id, 0.0)
            )
            for p in puntos
        ]
        registro = registro or self.registro
        if registro:
            filtros = {
                "tipos": [str(t) for t in tipos or []], "carrera": carrera,
                "solo_vigentes": solo_vigentes, "k": k,
            }
            registro(consulta, filtros, resultados, (time.perf_counter() - inicio) * 1000)
        return resultados
