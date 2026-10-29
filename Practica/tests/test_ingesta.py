from docx import Document
from docx.enum.text import WD_BREAK

from syllabusai.ingest.extraccion import Bloque, extraer
from syllabusai.ingest.segmentacion import segmentar


def test_docx_conserva_titulos_paginas_y_tablas(tmp_path):
    doc = Document()
    doc.add_heading("Reglamento", 1)
    doc.add_paragraph("Primer artículo del reglamento.")
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.add_heading("Evaluación", 2)
    tabla = doc.add_table(rows=2, cols=2)
    tabla.cell(0, 0).text, tabla.cell(0, 1).text = "Nivel", "Puntaje"
    tabla.cell(1, 0).text, tabla.cell(1, 1).text = "Crítico", "8,0–8,9"
    ruta = tmp_path / "r.docx"
    doc.save(str(ruta))

    bloques = extraer(ruta)
    assert [b.nivel_titulo for b in bloques] == [1, None, 2, None]
    assert bloques[-1].filas == [["Nivel", "Puntaje"], ["Crítico", "8,0–8,9"]]
    assert bloques[-1].pagina == 2


def test_pdf_detecta_titulos_por_tamano_y_quita_pies(tmp_path):
    import pymupdf

    capitulos = ["Introducción", "Fundamentos", "Metodología", "Resultados"]
    doc = pymupdf.open()
    for n, capitulo in enumerate(capitulos):
        pagina = doc.new_page()
        pagina.insert_text((72, 80), capitulo, fontsize=18)
        # El cuerpo cambia en cada página; lo que se repite en todas es encabezado o pie.
        pagina.insert_text((72, 120), f"El capítulo {capitulo.lower()} desarrolla su tema.", fontsize=11)
        pagina.insert_text((72, 140), f"Párrafo {n} con el tamaño de letra dominante.", fontsize=11)
        pagina.insert_text((72, 810), f"Universidad Indoamérica · página {n + 1}", fontsize=8)
    ruta = tmp_path / "d.pdf"
    doc.save(str(ruta))

    bloques = extraer(ruta)
    textos = [b.texto for b in bloques]
    assert not any("página" in t for t in textos)
    titulos = [b for b in bloques if b.nivel_titulo]
    assert [b.texto for b in titulos] == capitulos
    assert titulos[2].pagina == 3


def test_segmentacion_no_mezcla_secciones_y_respeta_el_maximo():
    bloques = [
        Bloque("Sección A", 1, nivel_titulo=1),
        *[Bloque(" ".join(["palabra"] * 30), 1) for _ in range(5)],
        Bloque("Sub A.1", 2, nivel_titulo=2),
        Bloque("texto corto", 2),
        Bloque("Sección B", 3, nivel_titulo=1),
        Bloque("otro texto", 3),
    ]
    fragmentos = segmentar(bloques, palabras_max=70, palabras_solape=30)
    assert all(len(f.texto.split()) <= 70 for f in fragmentos)
    rutas = [f.ruta_seccion for f in fragmentos]
    assert ["Sección A", "Sub A.1"] in rutas and ["Sección B"] in rutas
    # El solape repite el último párrafo del fragmento anterior.
    a = [f for f in fragmentos if f.ruta_seccion == ["Sección A"]]
    assert len(a) >= 2 and a[0].texto.split("\n")[-1] == a[1].texto.split("\n")[0]


def test_tabla_larga_se_divide_repitiendo_encabezado():
    filas = [["Código", "Descripción"]] + [[f"RA{i}", " ".join(["x"] * 20)] for i in range(10)]
    tabla = Bloque("\n".join(" | ".join(f) for f in filas), 1, filas=filas)
    fragmentos = segmentar([tabla], palabras_max=60)
    assert len(fragmentos) > 1
    assert all(f.texto.startswith("Código | Descripción") for f in fragmentos)
