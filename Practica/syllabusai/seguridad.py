"""Autenticación básica (RNF-08): contraseñas con PBKDF2 de la biblioteca estándar."""

import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from syllabusai.db.modelos import Rol, Usuario

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


def crear_usuario(sesion: Session, nombre: str, correo: str, contrasena: str, rol: Rol) -> Usuario:
    if sesion.scalar(select(Usuario).where(Usuario.correo == correo)) is not None:
        raise ValueError(f"Ya existe un usuario con el correo {correo}")
    usuario = Usuario(nombre=nombre, correo=correo, rol=rol, hash_contrasena=hash_contrasena(contrasena))
    sesion.add(usuario)
    sesion.flush()
    return usuario


def autenticar(sesion: Session, correo: str, contrasena: str) -> Usuario | None:
    usuario = sesion.scalar(select(Usuario).where(Usuario.correo == correo))
    if usuario is None or not verificar_contrasena(contrasena, usuario.hash_contrasena):
        return None
    return usuario
