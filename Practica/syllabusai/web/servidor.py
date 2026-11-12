"""Servidor de la página web: la API completa más el vigía de noticias en segundo plano.

    syllabusai web        # http://127.0.0.1:8080
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from syllabusai.api.app import contenedor_por_defecto, crear_app
from syllabusai.noticias.vigia import Vigia


def crear_app_web() -> FastAPI:
    app = crear_app()
    vigia = Vigia(contenedor_por_defecto(), contenedor_por_defecto().noticias)

    @asynccontextmanager
    async def ciclo(_: FastAPI):
        vigia.iniciar()
        yield
        vigia.detener()

    app.router.lifespan_context = ciclo
    app.state.vigia = vigia
    return app


app = crear_app_web()
