"""Autenticación (RNF-08): contraseñas con PBKDF2 de la biblioteca estándar y sesiones web.

La API acepta autenticación básica HTTP (clientes, pruebas) o la cookie de sesión de la web. De
la sesión solo se guarda el hash del token: quien lea la base no puede suplantar a nadie.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from syllabusai.db.modelos import Rol, SesionWeb, Usuario

ITERACIONES = 240_000


def hash_contrasena(contrasena: str) -> str:
    sal = secrets.token_hex(16)
    derivada = hashlib.pbkdf2_hmac("sha256", contrasena.encode(), bytes.fromhex(sal), ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${sal}${derivada.hex()}"


def verificar_contrasena(contrasena: str, almacenado: str) -> bool:
    try:
        _, iteraciones, sal, esperado = almacenado.split("$")
    except ValueError:
        return False
    derivada = hashlib.pbkdf2_hmac("sha256", contrasena.encode(), bytes.fromhex(sal), int(iteraciones))
    return hmac.compare_digest(derivada.hex(), esperado)


def crear_usuario(sesion: Session, nombre: str, correo: str, contrasena: str, rol: Rol,
                  carrera: str | None = None) -> Usuario:
    correo = correo.strip().lower()
    if sesion.scalar(select(Usuario).where(Usuario.correo == correo)) is not None:
        raise ValueError(f"Ya existe un usuario con el correo {correo}")
    usuario = Usuario(nombre=nombre, correo=correo, rol=rol, hash_contrasena=hash_contrasena(contrasena),
                      activo=True, carrera=carrera)
    sesion.add(usuario)
    sesion.flush()
    return usuario


def autenticar(sesion: Session, correo: str, contrasena: str) -> Usuario | None:
    usuario = sesion.scalar(select(Usuario).where(Usuario.correo == correo.strip().lower()))
    if usuario is None or not verificar_contrasena(contrasena, usuario.hash_contrasena):
        return None
    if usuario.activo is False:
        return None
    return usuario


def contrasena_temporal() -> str:
    """Contraseña inicial legible para entregar al docente (12 caracteres)."""
    alfabeto = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(12))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def abrir_sesion(sesion: Session, usuario: Usuario, horas: float) -> str:
    """Crea una sesión web y devuelve el token para la cookie."""
    ahora = datetime.now(UTC)
    sesion.execute(delete(SesionWeb).where(SesionWeb.expira < ahora.replace(tzinfo=None)))
    token = secrets.token_urlsafe(32)
    sesion.add(SesionWeb(token_hash=_hash_token(token), usuario_id=usuario.id,
                         expira=(ahora + timedelta(hours=horas)).replace(tzinfo=None)))
    sesion.flush()
    return token


def usuario_de_token(sesion: Session, token: str) -> Usuario | None:
    registro = sesion.scalar(select(SesionWeb).where(SesionWeb.token_hash == _hash_token(token)))
    if registro is None or registro.expira < datetime.now(UTC).replace(tzinfo=None):
        return None
    usuario = registro.usuario
    return None if usuario.activo is False else usuario


def cerrar_sesion(sesion: Session, token: str) -> None:
    sesion.execute(delete(SesionWeb).where(SesionWeb.token_hash == _hash_token(token)))
