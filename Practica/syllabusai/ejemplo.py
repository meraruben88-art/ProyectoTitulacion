"""Corpus de EJEMPLO para probar el prototipo de extremo a extremo sin la malla oficial.

Genera documentos DOCX ficticios y claramente marcados: perfil de egreso y malla de ITI (a partir
del catálogo de ejemplo), lineamientos de uso de IA en dos versiones (la de 2024 queda obsoleta,
para comprobar que el agente no la cita) y un sílabo aprobado de un periodo anterior. Las
competencias PE-xx-xx se transcriben de la ficha ITI-TFG-B26-0018; todo lo demás es ilustrativo.
"""

from pathlib import Path

import yaml
from docx import Document

from syllabusai.config import RAIZ

CATALOGO = RAIZ / "ejemplos" / "catalogo_iti_EJEMPLO.yaml"
MANIFIESTO = RAIZ / "ejemplos" / "manifiesto_EJEMPLO.yaml"
DESTINO = RAIZ / "data" / "ejemplo"

AVISO = ("DOCUMENTO DE EJEMPLO CON DATOS FICTICIOS, generado por SyllabusAI para pruebas. "
         "No es un documento oficial de la Universidad Tecnológica Indoamérica.")

# Nombres de archivo de cada documento generado. La malla lleva versión en el nombre: al ampliar
# el catálogo se genera un archivo nuevo y el registro deja obsoleta la versión anterior.
ARCHIVOS = {
    "perfil": "perfil_egreso_ITI_EJEMPLO.docx",
    "malla": "malla_ITI_EJEMPLO_v2.docx",
    "ia_2026": "lineamientos_IA_EJEMPLO_2026.docx",
    "ia_2024": "lineamientos_IA_EJEMPLO_2024.docx",
    "silabo_302": "silabo_aprobado_ITI-302_A25_EJEMPLO.docx",
}

# Competencias del perfil de egreso citadas en la ficha ITI-TFG-B26-0018 (Alineación institucional).
COMPETENCIAS = [
    ("PE-MI-05", ("Aplica teorías, metodologías, estándares y tecnologías apropiadas para crear "
                  "soluciones de software mediante el análisis, diseño, desarrollo, implementación, "
                  "verificación, documentación y gestión.")),
    ("PE-MI-06", ("Utiliza normas y estándares de calidad de ingeniería en tecnologías de la "
                  "información para garantizar que las implementaciones de software y hardware sean "
                  "robustas, confiables y adecuadas para el usuario.")),
    ("PE-IS-02", "Comunica sus soluciones de manera clara, precisa y correcta."),
    ("PE-IS-04", ("Realiza proyectos de investigación sobre problemas técnicos de la profesión e "
                  "innovaciones, siguiendo una metodología científica.")),
    ("PE-IS-06", "Posee creatividad para la innovación y el cambio tecnológico."),
    ("PE-PP-04", ("Desarrolla aplicaciones informáticas de vanguardia y sostenibles para procesar "
                  "información y automatizar procesos como soporte a las decisiones estratégicas.")),
]

# Referencias reales y verificables, asignadas a las asignaturas ficticias del ejemplo.
BIBLIOGRAFIA = {
    "ITI-501": [
        "Russell, S., & Norvig, P. (2021). Artificial Intelligence: A Modern Approach (4th ed.). Pearson.",
        "Goodfellow, I., Bengio, Y., & Courville, A. (2016). Deep Learning. MIT Press.",
        ("Géron, A. (2022). Hands-On Machine Learning with Scikit-Learn, Keras, and TensorFlow "
         "(3rd ed.). O'Reilly Media."),
    ],
    "ITI-302": [
        "Elmasri, R., & Navathe, S. B. (2016). Fundamentals of Database Systems (7th ed.). Pearson.",
        ("Silberschatz, A., Korth, H. F., & Sudarshan, S. (2020). Database System Concepts "
         "(7th ed.). McGraw-Hill."),
    ],
    "ITI-403": [
        "Sommerville, I. (2016). Software Engineering (10th ed.). Pearson.",
        ("Pressman, R. S., & Maxim, B. R. (2020). Software Engineering: A Practitioner's Approach "
         "(9th ed.). McGraw-Hill."),
    ],
    "ITI-604": [
        "Flanagan, D. (2020). JavaScript: The Definitive Guide (7th ed.). O'Reilly Media.",
        "Grinberg, M. (2018). Flask Web Development (2nd ed.). O'Reilly Media.",
        "Krug, S. (2014). Don't Make Me Think, Revisited (3rd ed.). New Riders.",
    ],
    "ITI-405": [
        ("Kurose, J. F., & Ross, K. W. (2021). Computer Networking: A Top-Down Approach (8th ed.). "
         "Pearson."),
        ("Tanenbaum, A. S., Feamster, N., & Wetherall, D. (2021). Computer Networks (6th ed.). "
         "Pearson."),
    ],
}

# Lineamientos de IA ficticios. La versión 2024 contradice a la de 2026 a propósito: si el agente
# la citara, la verificación lo detectaría como fuente obsoleta (RF-32).
LINEAMIENTOS_IA = {
    "2026": [
        ("Principios", (
            "El uso de inteligencia artificial generativa en la docencia se rige por la "
            "transparencia, la verificación humana, la protección de datos personales y la autoría "
            "demostrable del estudiante. Cada sílabo declara, por momento, la política de uso de IA."
        )),
        ("Usos autorizados en las evidencias", (
            "Los asistentes de IA autorizados pueden usarse para explorar alternativas, depurar "
            "código y revisar redacción. No se autoriza entregar como propio un producto generado "
            "íntegramente por IA. El docente puede declarar «No aplica» cuando la evidencia exige "
            "desempeño sin asistencia."
        )),
        ("Declaración de uso", (
            "El estudiante declara en cada evidencia la herramienta de IA utilizada, el propósito, "
            "las instrucciones empleadas y la verificación realizada."
        )),
        ("Datos que no se ingresan", (
            "No se ingresan en herramientas de IA datos personales de estudiantes, docentes o "
            "actores del territorio, ni información institucional reservada."
        )),
        ("Verificación y gobernanza ética", (
            "Los resultados de la IA se contrastan con fuentes verificables. La gobernanza ética de "
            "la inteligencia artificial forma parte de la evaluación socioformativa."
        )),
    ],
    "2024": [
        ("Principios", (
            "Versión anterior: el uso de herramientas de inteligencia artificial es libre y no "
            "requiere declaración en las evidencias."
        )),
        ("Usos autorizados en las evidencias", (
            "Se permite el uso de inteligencia artificial sin restricciones en todas las evidencias "
            "de evaluación."
        )),
    ],
}

SILABO_302 = [
    ("Planeación por momentos", (
        "Momento 1 (semanas 1–3): diagnóstico de los procesos de información de una unidad "
        "académica; evidencia: informe de requerimientos. Momento 2 (semanas 4–7): modelo "
        "entidad-relación y normalización; evidencia: modelo de datos documentado. Momento 3 "
        "(semanas 8–13): implementación en SQL con datos de prueba; evidencia: base de datos "
        "funcional con consultas verificadas. Momento 4 (semanas 14–16): defensa del producto "
        "integrador y metacognición."
    )),
    ("Evaluación", (
        "Momento 1: 20 %, momento 2: 30 %, momento 3: 30 %, momento 4: 20 %. Instrumento: rúbrica "
        "socioformativa con criterios de integridad de datos, normalización y seguridad. "
        "Coevaluación en los momentos 2 y 3. Una reentrega por evidencia parcial."
    )),
    ("Recursos y escenarios", (
        "Laboratorio de computación con PostgreSQL; escenario real: la secretaría académica de la "
        "sede (datos anonimizados)."
    )),
]


def _documento(titulo: str, secciones: list[tuple[str, str]], ruta: Path) -> Path:
    doc = Document()
    doc.add_heading(titulo, 0)
    doc.add_paragraph(AVISO)
    for encabezado, texto in secciones:
        doc.add_heading(encabezado, 1)
        doc.add_paragraph(texto)
    doc.save(str(ruta))
    return ruta


def generar_documentos(destino: Path = DESTINO, sobrescribir: bool = False) -> dict[str, Path]:
    """Genera los DOCX de ejemplo que falten. Los existentes no se tocan: regenerarlos cambia su
    huella y el registro los rechazaría como una versión repetida con otro contenido."""
    rutas = {clave: destino / nombre for clave, nombre in ARCHIVOS.items()}
    destino.mkdir(parents=True, exist_ok=True)

    def falta(clave: str) -> bool:
        return sobrescribir or not rutas[clave].exists()

    if falta("perfil"):
        perfil = Document()
        perfil.add_heading("Perfil de egreso — Ingeniería en Tecnologías de la Información (EJEMPLO)", 0)
        perfil.add_paragraph(AVISO)
        perfil.add_heading("Competencias específicas del perfil de egreso", 1)
        perfil.add_paragraph("El perfil de egreso de la carrera se expresa en competencias "
                             "específicas identificadas por su código:")
        for codigo, texto in COMPETENCIAS:
            perfil.add_paragraph(f"{codigo} -- {texto}")
        perfil.save(str(rutas["perfil"]))

    if falta("malla"):
        _malla(rutas["malla"])
    if falta("ia_2026"):
        _documento("Lineamientos para el uso de IA generativa en la docencia (EJEMPLO)",
                   LINEAMIENTOS_IA["2026"], rutas["ia_2026"])
    if falta("ia_2024"):
        _documento("Lineamientos para el uso de IA generativa en la docencia (EJEMPLO)",
                   LINEAMIENTOS_IA["2024"], rutas["ia_2024"])
    if falta("silabo_302"):
        _documento("Sílabo aprobado ITI-302 Bases de Datos, periodo A25 (EJEMPLO)", SILABO_302,
                   rutas["silabo_302"])
    return rutas


def _malla(ruta: Path) -> None:
    catalogo = yaml.safe_load(CATALOGO.read_text(encoding="utf-8"))["asignaturas"]
    malla = Document()
    malla.add_heading("Malla curricular y contenidos mínimos — ITI (EJEMPLO)", 0)
    malla.add_paragraph(AVISO)
    for a in catalogo:
        f = a["ficha"]
        malla.add_heading(f"{a['codigo']} {a['nombre']}", 1)
        tabla = malla.add_table(rows=0, cols=2)
        filas = [
            ("Código", a["codigo"]), ("Nivel", str(a["nivel"])),
            ("Unidad de organización curricular", f["unidad_organizacion"]),
            ("Créditos", str(a["creditos"])),
            ("Horas de contacto docente", str(f["horas_contacto"])),
            ("Horas práctico-experimentales", str(f["horas_practicas"])),
            ("Horas de aprendizaje autónomo", str(f["horas_autonomas"])),
            ("Total de horas", str(a["horas"])),
            ("Prerrequisitos", ", ".join(a["prerrequisitos"])),
        ]
        for campo, valor in filas:
            celdas = tabla.add_row().cells
            celdas[0].text, celdas[1].text = campo, valor
        malla.add_heading(f"Resultados de aprendizaje de {a['nombre']}", 2)
        for ra in f["resultados_aprendizaje"]:
            malla.add_paragraph(f"{ra['codigo']}: {ra['enunciado']}")
        malla.add_heading(f"Contenidos mínimos de {a['nombre']}", 2)
        for i, contenido in enumerate(f["contenidos_minimos"], start=1):
            malla.add_paragraph(f"{i}. {contenido}.")
        malla.add_heading(f"Bibliografía básica de {a['nombre']}", 2)
        for referencia in BIBLIOGRAFIA.get(a["codigo"], []):
            malla.add_paragraph(referencia)
    malla.save(str(ruta))
