"""Construcción de los componentes del prototipo a partir de la configuración."""

import sqlite3
from dataclasses import dataclass

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy.orm import Session, sessionmaker

from syllabusai.agent.grafo import Orquestador
from syllabusai.agent.servicio import ServicioSilabos
from syllabusai.config import Config, cargar_config
from syllabusai.db.sesion import crear_fabrica_sesiones, crear_motor, crear_tablas
from syllabusai.formato.definicion import Formato, cargar_formato
from syllabusai.llm import crear_cliente
from syllabusai.llm.base import ClienteLLM
from syllabusai.noticias.servicio import ServicioNoticias
from syllabusai.pis.servicio import ServicioPIS
from syllabusai.retrieval.almacen import AlmacenVectorial
from syllabusai.retrieval.codificadores import CodificadorDenso, crear_codificador
from syllabusai.retrieval.recuperador import Recuperador


@dataclass
class Contenedor:
    config: Config
    fabrica: sessionmaker[Session]
    formato: Formato
    recuperador: Recuperador
    llm: ClienteLLM
    servicio: ServicioSilabos
    orquestador: Orquestador
    pis: ServicioPIS
    noticias: ServicioNoticias

    def cambiar_llm(self, llm: ClienteLLM) -> None:
        """Usa otro modelo en todos los servicios (p. ej. al pasar del simulado a NVIDIA)."""
        self.llm = self.servicio.llm = self.pis.llm = self.noticias.llm = llm

    def cerrar(self) -> None:
        self.recuperador.almacen.cerrar()


def crear_contenedor(
    config: Config | None = None,
    *,
    llm: ClienteLLM | None = None,
    codificador: CodificadorDenso | None = None,
    checkpoints_en_memoria: bool = False,
) -> Contenedor:
    config = config or cargar_config()
    motor = crear_motor(config.base_datos.url)
    crear_tablas(motor)
    fabrica = crear_fabrica_sesiones(motor)
    formato = cargar_formato(config.formato)
    codificador = codificador if codificador is not None else crear_codificador(config.embeddings)
    almacen = AlmacenVectorial.abrir(
        config.base_vectorial, codificador.dimension if codificador else None
    )
    recuperador = Recuperador(almacen, codificador, config.recuperacion)
    llm = llm or crear_cliente(config.llm)
    servicio = ServicioSilabos(fabrica, recuperador, llm, formato, config)
    if checkpoints_en_memoria:
        checkpointer = InMemorySaver()
    else:
        config.agente.checkpoints.parent.mkdir(parents=True, exist_ok=True)
        conexion = sqlite3.connect(config.agente.checkpoints, check_same_thread=False)
        checkpointer = SqliteSaver(conexion)
    orquestador = Orquestador(servicio, checkpointer)
    pis = ServicioPIS(fabrica, recuperador, llm, config)
    noticias = ServicioNoticias(fabrica, recuperador, llm)
    return Contenedor(config, fabrica, formato, recuperador, llm, servicio, orquestador, pis, noticias)
