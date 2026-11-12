from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from syllabusai.config import RAIZ
from syllabusai.db.modelos import (
    Asignatura,
    Documento,
    FuenteNoticias,
    Malla,
    TipoDocumento,
    Usuario,
)
from syllabusai.ingest.reparacion import reparar
from syllabusai.noticias.vigia import Vigia, entradas_rss, texto_visible

MALLA_ITI = next((RAIZ / "MALLAS").glob("*TecnologiasDeLaInformacion.pdf"), None)


@pytest.mark.parametrize("roto, reparado", [
    ("R e s u e l v e problemas d e electrostátic a   y electromag n e t i s m o",
     "Resuelve problemas de electrostática y electromagnetismo"),
    ("COMPUTAC I O N Y SOCIEDAD", "COMPUTACION Y SOCIEDAD"),
    ("FUNDAMEN TOSDELAS BASES DE DATOS", "FUNDAMENTOS DE LAS BASES DE DATOS"),
    ("Nombredela asignatura", "Nombre de la asignatura"),
    ("en un plano y  d o s p l a n o s aplicando propiedades", "en un plano y dos planos aplicando propiedades"),
])
def test_reparacion_del_texto_del_ces(roto, reparado):
    assert reparar(roto) == reparado


@pytest.mark.skipif(MALLA_ITI is None, reason="falta la malla de ITI en MALLAS/")
def test_extraccion_de_la_malla_de_iti():
    from syllabusai.ingest.mallas import extraer_malla

    malla = extraer_malla(MALLA_ITI)
    assert malla.perfil.sigla == "ITI" and len(malla.asignaturas) >= 38
    fisica = next(a for a in malla.asignaturas if a.nombre.startswith("Fisica"))
    assert (fisica.nivel, fisica.horas_contacto, fisica.horas_practicas, fisica.horas_autonomas) == (1, 64, 64, 16)
    assert len(fisica.resultados) == 3 and fisica.resultados[0].startswith("Resuelve problemas de vectores")
    assert "Cinemática" in fisica.contenidos
    # Las horas que el CES declara cuadran en las asignaturas con docencia.
    con_docencia = [a for a in malla.asignaturas if a.horas_contacto]
    assert all(a.horas_contacto + a.horas_practicas + a.horas_autonomas == a.total for a in con_docencia)


@pytest.mark.skipif(MALLA_ITI is None, reason="falta la malla de ITI en MALLAS/")
def test_importar_malla_crea_corpus_perfil_y_fichas(contenedor):
    from syllabusai.ingest.importar_mallas import importar_malla

    c = contenedor
    with c.fabrica() as s:
        admin = s.scalar(select(Usuario).where(Usuario.correo == "admin@uti.test"))
        malla, extraida = importar_malla(s, c, MALLA_ITI, admin.id)
        s.commit()
        assert extraida is not None and malla.documento.tipo == TipoDocumento.MALLA
        perfil = s.scalar(select(Documento).where(Documento.tipo == TipoDocumento.PERFIL_EGRESO,
                                                  Documento.carrera == "ITI", Documento.titulo.like("%malla CES%")))
        assert perfil is not None and c.recuperador.almacen.contar(perfil.id) > 0
        fisica = s.scalar(select(Asignatura).where(Asignatura.malla_id == malla.id, Asignatura.nombre.like("Fisica%")))
        assert fisica.codigo == "ITI-0103" and not fisica.revisada and fisica.origen == "malla_ces"
        assert fisica.horas == 144 and len(fisica.ficha["resultados_aprendizaje"]) == 3
        # El catálogo de ejemplo queda marcado como tal.
        assert s.scalar(select(Asignatura).where(Asignatura.codigo == "ITI-501")).origen == "ejemplo"
        # Reimportar no duplica nada.
        otra, sin_cambios = importar_malla(s, c, MALLA_ITI, admin.id)
        assert otra.id == malla.id and sin_cambios is None
        assert len(s.scalars(select(Malla)).all()) == 1


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>UTI</title>
{items}</channel></rss>"""
ITEM = "<item><guid>{n}</guid><title>Noticia {n}</title><link>https://uti.test/{n}</link><description>&lt;p&gt;Texto {n} sobre el sílabo&lt;/p&gt;</description></item>"


def test_rss_y_texto_visible():
    entradas = entradas_rss(RSS.format(items=ITEM.format(n=1)))
    assert entradas == [{"id": "1", "titulo": "Noticia 1", "url": "https://uti.test/1",
                         "resumen": "Texto 1 sobre el sílabo"}]
    assert texto_visible("<html><script>x()</script><h1>Hola</h1><p>mundo</p></html>").split() == ["Hola", "mundo"]


def test_vigia_publica_lo_nuevo_de_las_fuentes(contenedor, tmp_path):
    c = contenedor
    c.config.noticias.bandeja = tmp_path / "bandeja"
    respuestas = {"rss": RSS.format(items=ITEM.format(n=1)), "pagina": "<p>Calendario A</p>"}
    transporte = httpx.MockTransport(lambda r: httpx.Response(200, text=respuestas[r.url.path.strip("/")]))
    vigia = Vigia(c, c.noticias, httpx.Client(transport=transporte))
    with c.fabrica() as s:
        s.add_all([FuenteNoticias(nombre="Noticias UTI", url="https://uti.test/rss", tipo="rss", vistos=[]),
                   FuenteNoticias(nombre="Calendario", url="https://uti.test/pagina", tipo="pagina", vistos=[])])
        s.commit()
    assert vigia.ronda() == []  # la primera ronda solo toma la línea base
    respuestas["rss"] = RSS.format(items=ITEM.format(n=2) + ITEM.format(n=1))
    respuestas["pagina"] = "<p>Calendario B</p>"
    publicadas = vigia.ronda()
    assert sorted(n["titulo"] for n in publicadas) == ["Cambió la página «Calendario»", "Noticia 2"]
    assert all(n["categoria"] == "externa" for n in publicadas)
    assert vigia.ronda() == []


def test_vigia_ingiere_la_bandeja(contenedor, tmp_path):
    from conftest import escribir_normativa

    c = contenedor
    bandeja = tmp_path / "bandeja"
    bandeja.mkdir()
    c.config.noticias.bandeja = bandeja
    escribir_normativa(bandeja / "Reglamento_de_evaluacion.docx", "Versión de la bandeja")
    (bandeja / "Reglamento_de_evaluacion.yaml").write_text(
        "titulo: Reglamento de evaluación\ntipo: normativa\nversion: '2026'\nfecha_vigencia: 2026-05-01\n", encoding="utf-8")
    publicadas = Vigia(c, c.noticias).revisar_bandeja()
    assert [n["titulo"] for n in publicadas] == ["Nuevo documento: Reglamento de evaluación"]
    assert (bandeja / "procesados" / "Reglamento_de_evaluacion.docx").exists()
    assert not list(Path(bandeja).glob("*.docx"))
