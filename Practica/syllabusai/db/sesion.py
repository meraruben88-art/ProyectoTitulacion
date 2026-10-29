"""Motor y sesiones de la base relacional."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from syllabusai.config import RAIZ
from syllabusai.db.modelos import Base


def crear_motor(url: str) -> Engine:
    opciones = {}
    partes = make_url(url)
    if partes.get_backend_name() == "sqlite":
        if partes.database in (None, "", ":memory:"):
            # Una sola conexión compartida: si no, cada conexión vería una base vacía.
            opciones = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        else:
            ruta = Path(partes.database)
            if not ruta.is_absolute():
                ruta = RAIZ / ruta
                url = partes.set(database=str(ruta)).render_as_string(hide_password=False)
            ruta.parent.mkdir(parents=True, exist_ok=True)

    motor = create_engine(url, **opciones)

    if partes.get_backend_name() == "sqlite":
        # SQLite no aplica las claves foráneas salvo que se active en cada conexión.
        @event.listens_for(motor, "connect")
        def _activar_claves_foraneas(conexion, _registro):
            conexion.execute("PRAGMA foreign_keys=ON")

    return motor


def crear_tablas(motor: Engine) -> None:
    Base.metadata.create_all(motor)
    _agregar_columnas_nuevas(motor)


def _agregar_columnas_nuevas(motor: Engine) -> None:
    """Migración mínima: añade las columnas anulables que una base anterior todavía no tiene."""
    existentes = inspect(motor)
    with motor.begin() as conexion:
        for tabla in Base.metadata.sorted_tables:
            if not existentes.has_table(tabla.name):
                continue
            presentes = {c["name"] for c in existentes.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name not in presentes and columna.nullable:
                    tipo = columna.type.compile(dialect=motor.dialect)
                    conexion.execute(text(f'ALTER TABLE {tabla.name} ADD COLUMN "{columna.name}" {tipo}'))


def crear_fabrica_sesiones(motor: Engine) -> sessionmaker[Session]:
    return sessionmaker(motor, expire_on_commit=False)
