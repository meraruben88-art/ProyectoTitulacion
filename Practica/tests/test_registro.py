from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from syllabusai.config import cargar_config
from syllabusai.db.modelos import Documento, EstadoDocumento, TipoDocumento
from syllabusai.esquemas import PayloadFragmento
from syllabusai.ingest.registro import (
    ErrorRegistro,
    cambiar_estado,
    documentos_vigentes,
    registrar_documento,
)


@pytest.fixture
def registrar(sesion, admin, tmp_path):
    def _registrar(archivo, meta):
        return registrar_documento(sesion, archivo, meta, admin.id, tmp_path / "corpus")

    return _registrar


def test_registra_y_copia_al_corpus(registrar, archivo, meta):
    doc = registrar(archivo(), meta())
    assert doc.estado == EstadoDocumento.VIGENTE
    assert len(doc.hash_archivo) == 64
    assert Path(doc.ruta).read_bytes() == b"%PDF-1.7 v1"


def test_version_nueva_deja_obsoleta_la_anterior_sin_borrarla(sesion, registrar, archivo, meta):
    v1 = registrar(archivo(), meta())
    # Mismo documento aunque el título llegue con otras mayúsculas y espacios.
    v2 = registrar(
        archivo("reglamento_2026.pdf", b"%PDF-1.7 v2"),
        meta(titulo="  reglamento de  régimen académico", version="2026", fecha_vigencia=date(2026, 3, 1)),
    )
    assert (v1.estado, v2.estado) == (EstadoDocumento.OBSOLETO, EstadoDocumento.VIGENTE)
    assert sesion.scalar(select(func.count()).select_from(Documento)) == 2
    assert Path(v1.ruta).exists()
    assert documentos_vigentes(sesion) == [v2]


def test_version_historica_entra_como_obsoleta(registrar, archivo, meta):
    actual = registrar(archivo(), meta())
    vieja = registrar(
        archivo("reglamento_2019.pdf", b"%PDF-1.7 v0"),
        meta(version="2019", fecha_vigencia=date(2019, 3, 1)),
    )
    assert (actual.estado, vieja.estado) == (EstadoDocumento.VIGENTE, EstadoDocumento.OBSOLETO)


def test_documentos_distintos_no_se_afectan(sesion, registrar, archivo, meta):
    registrar(archivo(), meta())
    registrar(archivo("malla.docx", b"docx"), meta(titulo="Malla curricular", tipo=TipoDocumento.MALLA))
    registrar(archivo("reg_sis.pdf", b"otra carrera"), meta(carrera="SIS"))
    assert len(documentos_vigentes(sesion)) == 3
    assert [d.titulo for d in documentos_vigentes(sesion, tipo=TipoDocumento.MALLA)] == ["Malla curricular"]
    assert [d.carrera for d in documentos_vigentes(sesion, carrera="SIS")] == ["SIS"]


def test_rechaza_duplicados_versiones_repetidas_y_formatos(registrar, archivo, meta):
    registrar(archivo(), meta())
    with pytest.raises(ErrorRegistro, match="ya está en el corpus"):
        registrar(archivo("copia.pdf"), meta(version="2026"))
    with pytest.raises(ErrorRegistro, match="Ya existe la versión"):
        registrar(archivo("otro.pdf", b"contenido distinto"), meta())
    with pytest.raises(ErrorRegistro, match="Formato no admitido"):
        registrar(archivo("notas.txt", b"texto"), meta(titulo="Notas"))


def test_cambiar_estado_mantiene_una_sola_version_vigente(sesion, registrar, archivo, meta):
    v1 = registrar(archivo(), meta())
    v2 = registrar(
        archivo("r2.pdf", b"%PDF-1.7 v2"), meta(version="2026", fecha_vigencia=date(2026, 3, 1))
    )
    cambiar_estado(sesion, v1.id, EstadoDocumento.VIGENTE)
    assert documentos_vigentes(sesion) == [v1]
    cambiar_estado(sesion, v1.id, EstadoDocumento.OBSOLETO)
    assert documentos_vigentes(sesion) == [] and v2.estado == EstadoDocumento.OBSOLETO
    with pytest.raises(ErrorRegistro):
        cambiar_estado(sesion, 999, EstadoDocumento.VIGENTE)


def test_payload_de_fragmento_valida_paginas():
    base = {
        "fragmento_id": "f-1", "documento_id": 1, "tipo_documento": "normativa", "carrera": "ITI",
        "version": "2025", "vigente": True, "titulo": "Reglamento", "texto": "Art. 1 ...",
    }
    ok = PayloadFragmento(**base, ruta_seccion=["Título I", "Art. 1"], pagina_inicio=3, pagina_fin=4)
    assert ok.tipo_documento == TipoDocumento.NORMATIVA
    with pytest.raises(ValidationError):
        PayloadFragmento(**base, pagina_inicio=4, pagina_fin=3)


def test_config_por_defecto():
    config = cargar_config()
    assert config.base_datos.url.startswith("sqlite:///")
    assert config.corpus.directorio.is_absolute()
    assert config.corpus.extensiones == [".pdf", ".docx"]
