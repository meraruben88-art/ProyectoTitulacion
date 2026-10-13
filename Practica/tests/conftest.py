from datetime import date

import pytest

from syllabusai.db.modelos import Rol, TipoDocumento, Usuario
from syllabusai.db.sesion import crear_fabrica_sesiones, crear_motor, crear_tablas
from syllabusai.esquemas import MetadatosDocumento


@pytest.fixture
def sesion():
    motor = crear_motor("sqlite://")
    crear_tablas(motor)
    with crear_fabrica_sesiones(motor)() as s:
        yield s


@pytest.fixture
def admin(sesion):
    usuario = Usuario(
        nombre="Admin", correo="admin@uti.edu.ec", rol=Rol.ADMIN_CORPUS, hash_contrasena="x"
    )
    sesion.add(usuario)
    sesion.flush()
    return usuario


@pytest.fixture
def meta():
    def _meta(**cambios):
        base = {
            "titulo": "Reglamento de Régimen Académico",
            "tipo": TipoDocumento.NORMATIVA,
            "carrera": "ITI",
            "version": "2025",
            "fecha_vigencia": date(2025, 3, 1),
        }
        return MetadatosDocumento(**(base | cambios))

    return _meta


@pytest.fixture
def archivo(tmp_path):
    def _archivo(nombre="reglamento.pdf", contenido=b"%PDF-1.7 v1"):
        ruta = tmp_path / "origen" / nombre
        ruta.parent.mkdir(exist_ok=True)
        ruta.write_bytes(contenido)
        return ruta

    return _archivo
