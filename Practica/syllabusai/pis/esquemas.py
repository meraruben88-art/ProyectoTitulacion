"""Contenido del PIS según la «Guía metodológica, instructivo y plantilla de construcción de PIS»
(UTI, Vicerrectorado Académico), sección 12: formato de presentación institucional.

Cada campo es el producto de un paso del instructivo (sección 7). Los esquemas son permisivos:
el docente puede dejar campos a medias; los criterios de validación (sección 9 de la guía) dicen
qué falta.
"""

from pydantic import BaseModel, Field

from syllabusai.formato.catalogos import NIVELES_RUBRICA

ETAPAS = ("Comprensión y diagnóstico", "Análisis", "Diseño o desarrollo", "Validación", "Socialización")


class FilaArticulacion(BaseModel):
    """Una fila de la matriz de articulación (7.4): un RAP que un PF aporta al proyecto."""

    competencia: str = Field("", description="Competencia del perfil de egreso que el RAP ayuda a lograr.")
    pf: str = Field("", description="Proyecto Formativo (asignatura) que participa.")
    rap: str = Field("", description="Resultado de aprendizaje existente de ese PF (código y enunciado).")
    aporte: str = Field("", description="Qué hace ese RAP dentro del proyecto, en una frase.")
    momento: str = Field("", description="Etapa de la actuación en que entra el PF.")
    evidencia_parcial: str = Field("", description="Producto concreto que entrega el PF.")


class Investigacion(BaseModel):
    """7.5, parte 1: diseño de la investigación."""

    pregunta: str = ""
    enfoque: str = ""
    fuentes_tecnicas: str = ""
    hallazgos_esperados: str = ""


class EtapaActuacion(BaseModel):
    """7.5, parte 2: etapas encadenadas de la actuación."""

    etapa: str = ""
    actuacion: str = ""
    aporte_pf: str = ""
    resultado: str = Field("", description="Resultado que alimenta la etapa siguiente.")


class Actividad(BaseModel):
    """7.7: plan de actividades y cronograma."""

    semana: str = ""
    etapa: str = ""
    actividad: str = ""
    pf_rap: str = ""
    responsable: str = ""
    evidencia: str = ""


class Rol(BaseModel):
    actor: str = ""
    responsabilidades: str = ""


class ProyectoIntegrador(BaseModel):
    # 1. Identificación del PIS
    titulo: str = ""
    carrera: str = ""
    periodo: str = ""
    nivel: str = ""
    equipo_docente: list[str] = []
    # 2-3. Problema del contexto y justificación (ficha del problema, 7.1)
    problema: str = ""
    contexto: str = ""
    justificacion: str = ""
    pregunta_reto: str = ""
    delimitacion: str = ""
    # 4. Propósito (7.3): Diseñar / analizar / desarrollar / validar ___ para ___, considerando ___.
    proposito: str = ""
    # 5-7. Competencias, PF participantes y matriz de articulación (7.2, 7.4)
    competencias: list[str] = []
    pf_participantes: list[str] = []
    articulacion: list[FilaArticulacion] = []
    # Lo que aporta este Proyecto Formativo (el del sílabo) al PIS: RA y producto, sin horas.
    aporte_este_pf: str = ""
    # 8. Evidencia integradora (7.6)
    evidencia_integradora: str = ""
    aportes_integrados: str = ""
    criterios_logro: list[str] = []
    # 9. Fases y metodología (7.5)
    investigacion: Investigacion = Investigacion()
    etapas: list[EtapaActuacion] = []
    # 10. Plan de actividades y cronograma (7.7)
    cronograma: list[Actividad] = []
    # 11. Roles y responsabilidades (sección 8)
    roles: list[Rol] = []
    # 12. Evaluación (7.8): la escala y la rúbrica de integración son institucionales.
    evaluacion: str = ""
    # 13. Recursos y condiciones
    recursos: str = ""
    # 14. Socialización
    socializacion: str = ""
    # 15. Reflexión y mejora (7.9)
    reflexion: list[str] = []
    # 16. Resultados e impacto esperado
    impacto: str = ""
    # Sección 10: prueba de interdisciplinariedad
    prueba_interdisciplinariedad: str = ""


class SalidaPIS(BaseModel):
    contenido: ProyectoIntegrador
    fuentes: list[str] = []
    abstencion: str | None = None
    notas: str | None = None


PREGUNTAS_REFLEXION = [
    "¿Qué comprendimos del problema?",
    "¿Cómo se integraron los aportes de los diferentes PF?",
    "¿Qué nos aportó el proceso de investigación y qué decisiones fueron determinantes?",
    "¿Qué dificultades enfrentamos y qué debemos mejorar?",
    "¿Qué impacto tendría la propuesta en el contexto?",
]

ROLES_GUIA = [
    Rol(actor="Coordinación de carrera", responsabilidades=(
        "Validar pertinencia, coordinar la planificación, asegurar la articulación curricular y "
        "gestionar condiciones.")),
    Rol(actor="Coordinador del PIS", responsabilidades=(
        "Liderar el cronograma, articular a los docentes, monitorear avances y consolidar la "
        "evidencia integradora.")),
    Rol(actor="Docentes de PF", responsabilidades=(
        "Desarrollar los RAP, aportar conocimientos y procedimientos, producir evidencias parciales "
        "y retroalimentar.")),
    Rol(actor="Estudiantes", responsabilidades=(
        "Investigar, analizar, tomar decisiones, integrar aportes, construir la evidencia y "
        "reflexionar.")),
]

ESCALA = "; ".join(f"{n.numero} {n.nombre}" for n in NIVELES_RUBRICA)
EVALUACION_GUIA = (
    "Se valoran dos objetos en la escala socioformativa institucional de cinco niveles "
    f"({ESCALA}), con acreditación desde el nivel Crítico: (1) el logro de los RAP, que cada PF "
    "evalúa con sus propios instrumentos, y (2) la integración interdisciplinaria, que el equipo "
    "del PIS valora sobre la evidencia integradora con la rúbrica de integración (comprensión del "
    "problema, proceso de investigación, integración de saberes, pertinencia de la respuesta, "
    "calidad de la evidencia, argumentación y decisiones, reflexión y mejora)."
)


def pis_vacio() -> dict:
    return ProyectoIntegrador().model_dump(mode="json")
