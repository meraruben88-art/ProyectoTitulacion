"""Listas cerradas del formato institucional 2026.

Fuente: «Propuesta técnica para el nuevo sílabo de Proyecto Formativo» (UTI, agosto 2026),
secciones 3.3, 3.4, 7.6, 7.7 y 10, armonizada con el Modelo Educativo Institucional 2026
(Tablas 3 y 4). Estos valores no los decide el modelo de lenguaje.
"""

from dataclasses import dataclass

METACOMPETENCIAS = (
    "Pensamiento sociocrítico y sistémico para la toma de decisiones estratégicas",
    "Gobernanza ética de tecnologías digitales e IA",
    "Innovación y emprendimiento sostenible con impacto territorial",
    "Metacognición estratégica y proyecto ético de vida",
    "Liderazgo colaborativo e intercultural para la transformación territorial",
)

EJES = (
    "Formación integral, inclusión y desarrollo humano",
    "Territorialización, innovación y emprendimiento disruptivo",
    "Pensamiento complejo e interdisciplinariedad",
    "Interculturalidad crítica, justicia cognitiva e internacionalización",
    "Transformación digital y gobernanza ética de la inteligencia artificial",
    "Evaluación socioformativa y gestión basada en evidencias",
    "Ecosistema institucional de aprendizaje y experiencia universitaria",
)

# Lista institucional sugerida; el formato admite «otra aprobada» con evidencia asociada.
HABILIDADES_BLANDAS = (
    "Comunicación efectiva",
    "Trabajo colaborativo",
    "Liderazgo",
    "Adaptabilidad",
    "Empatía",
    "Autorregulación",
    "Pensamiento crítico",
    "Resolución de problemas",
)

TIPOS_EVALUACION = ("heteroevaluacion", "coevaluacion", "autoevaluacion")


@dataclass(frozen=True)
class NivelRubrica:
    numero: int
    nombre: str
    descriptor: str
    minimo: float
    maximo: float
    equivalencia: str


NIVELES_RUBRICA = (
    NivelRubrica(1, "Receptivo", "Reconoce conceptos y escucha actores; sin autoría verificable "
                 "ni territorio.", 0.0, 5.9, "Reprobado / inicial"),
    NivelRubrica(2, "Resolutivo", "Aplica procedimientos básicos; autoría parcial demostrada.",
                 6.0, 6.9, "Aprobación mínima"),
    NivelRubrica(3, "Reflexivo", "Analiza implicaciones, reflexiona sobre su rol y articula "
                 "teoría-práctica.", 7.0, 7.9, "Suficiente"),
    NivelRubrica(4, "Crítico", "Problematiza causas estructurales con enfoque sistémico y proceso "
                 "propio verificable.", 8.0, 8.9, "Notable / microcredencial según regulación "
                 "institucional"),
    NivelRubrica(5, "Cocreativo", "Cocrea con actores y orienta transformación territorial con "
                 "ética e innovación.", 9.0, 10.0, "Sobresaliente"),
)


@dataclass(frozen=True)
class MomentoBase:
    numero: int
    nombre: str
    # Proporción de las horas de cada componente que se asigna por defecto al momento.
    proporcion: float
    # Peso orientador de la evaluación del momento (porcentaje mínimo y máximo).
    peso_min: int
    peso_max: int
    peso_sugerido: int


# Los momentos inicial y final son más breves; los centrales concentran diseño y resolución
# (Propuesta 2026, paso 9). Los pesos sugeridos suman 100 y respetan los rangos orientadores.
MOMENTOS = (
    MomentoBase(1, "Sensibilización, contextualización y conceptualización", 0.22, 20, 25, 20),
    MomentoBase(2, "Planeación y diseño de la resolución", 0.26, 25, 30, 30),
    MomentoBase(3, "Resolución / implementación del problema del contexto", 0.34, 25, 30, 30),
    MomentoBase(4, "Integración, socialización, metacognición y mejora", 0.18, 20, 25, 20),
)

# Verbos de baja complejidad que la Propuesta 2026 pide evitar en resultados y desempeños.
VERBOS_TEMATICOS = ("conocer", "comprender", "entender", "saber", "aprender")

# Hasta 3 oportunidades de mejora del producto final y 1 de los parciales (Propuesta 2026, 7.6).
MAX_MEJORAS_FINAL = 3
MAX_MEJORAS_PARCIAL = 1
