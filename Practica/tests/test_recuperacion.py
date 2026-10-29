import pytest

from syllabusai.agent.herramientas import candidatos_bibliografia, evidencia_suficiente
from syllabusai.config import ConfigRecuperacion
from syllabusai.db.modelos import TipoDocumento as T
from syllabusai.esquemas import PayloadFragmento
from syllabusai.retrieval.almacen import AlmacenVectorial, ErrorAlmacen
from syllabusai.retrieval.codificadores import CodificadorHash
from syllabusai.retrieval.lexico import tokenizar
from syllabusai.retrieval.recuperador import FragmentoRecuperado, Recuperador


def test_tokenizador_conserva_codigos_y_quita_tildes():
    tokens = tokenizar("La competencia PE-MI-05 de evaluación")
    assert "pe-mi-05" in tokens and "evaluacion" in tokens and "la" not in tokens


def _fragmento(n, texto, tipo=T.NORMATIVA, carrera="TODAS", vigente=True, ruta=None):
    return PayloadFragmento(
        fragmento_id=f"d{n}-f0001", documento_id=n, tipo_documento=tipo, carrera=carrera,
        version="1", vigente=vigente, titulo=f"Documento {n}", ruta_seccion=ruta or [],
        pagina_inicio=1, pagina_fin=1, texto=texto,
    )


@pytest.fixture(params=[None, CodificadorHash(64)], ids=["lexico", "hibrido"])
def recuperador(request):
    from qdrant_client import QdrantClient

    codificador = request.param
    almacen = AlmacenVectorial(QdrantClient(":memory:"), "t", codificador.dimension if codificador else None)
    r = Recuperador(almacen, codificador, ConfigRecuperacion())
    r.indexar([
        _fragmento(1, "Política de evaluación: la rúbrica tiene cinco niveles."),
        _fragmento(2, "Competencia PE-MI-05 del perfil de egreso.", T.PERFIL_EGRESO, "ITI"),
        _fragmento(3, "Política de evaluación anterior, derogada.", vigente=False),
        _fragmento(4, "Competencia PE-MI-05 de otra carrera.", T.PERFIL_EGRESO, "DER"),
    ])
    return r


def test_filtra_por_vigencia_tipo_y_carrera(recuperador):
    ids = [r.fragmento.fragmento_id for r in recuperador.buscar("política de evaluación")]
    assert "d1-f0001" in ids and "d3-f0001" not in ids
    con_obsoletos = recuperador.buscar("política de evaluación", solo_vigentes=False)
    assert "d3-f0001" in [r.fragmento.fragmento_id for r in con_obsoletos]
    perfil = recuperador.buscar("PE-MI-05", tipos=[T.PERFIL_EGRESO], carrera="ITI")
    assert [r.fragmento.fragmento_id for r in perfil] == ["d2-f0001"]


def test_registra_cada_consulta(recuperador):
    vistas = []
    recuperador.buscar("rúbrica", registro=lambda *a: vistas.append(a))
    consulta, filtros, _, latencia = vistas[0]
    assert consulta == "rúbrica" and filtros["solo_vigentes"] and latencia >= 0


def test_marcar_obsoleto_saca_al_documento_de_la_busqueda(recuperador):
    assert recuperador.buscar("rúbrica cinco niveles")[0].fragmento.documento_id == 1
    recuperador.almacen.marcar_vigencia(1, False)
    assert all(r.fragmento.documento_id != 1 for r in recuperador.buscar("rúbrica cinco niveles"))


def test_no_mezcla_dimensiones_de_embeddings():
    from qdrant_client import QdrantClient

    cliente = QdrantClient(":memory:")
    AlmacenVectorial(cliente, "t", None)
    with pytest.raises(ErrorAlmacen):
        AlmacenVectorial(cliente, "t", 64)


def test_abstencion_por_tipo_sin_coincidencias():
    fr = [FragmentoRecuperado(_fragmento(1, "x"), 1.0, 2.0),
          FragmentoRecuperado(_fragmento(2, "y", T.PERFIL_EGRESO), 1.0, 0.0)]
    assert evidencia_suficiente(fr, [T.NORMATIVA, T.PERFIL_EGRESO], 1) == [T.PERFIL_EGRESO]


def test_bibliografia_solo_de_la_asignatura():
    texto_ia = "Russell, S., & Norvig, P. (2021). Artificial Intelligence. Pearson."
    texto_bd = "Elmasri, R. (2016). Fundamentals of Database Systems. Pearson."
    fr = [
        FragmentoRecuperado(_fragmento(1, texto_ia, T.MALLA, "ITI",
                                       ruta=["Bibliografía básica de Inteligencia Artificial"]), 1, 1),
        FragmentoRecuperado(_fragmento(2, texto_bd, T.MALLA, "ITI",
                                       ruta=["Bibliografía básica de Bases de Datos"]), 1, 1),
    ]
    assert candidatos_bibliografia([], fr, "Inteligencia Artificial") == [texto_ia]
