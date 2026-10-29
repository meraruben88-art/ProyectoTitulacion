"""Contenido de cada sección del sílabo (formato 2026) como datos validados.

Cada sección se guarda en `version_seccion.contenido` con su esquema, de modo que las reglas
de coherencia (RF-33, RF-34) trabajan sobre datos y la exportación rellena el formato sin
volver a pasar por el modelo (SPEC, sección 8). Los esquemas son deliberadamente permisivos:
un campo vacío no impide guardar la propuesta; lo señalan las reglas de completitud (RF-31).
"""

from pydantic import BaseModel, Field


class Identificacion(BaseModel):
    """7.1 Información general. Todo se importa de la ficha curricular, salvo el docente."""

    nombre_pf: str = ""
    codigo: str = ""
    version: str = "1"
    facultad: str = ""
    carrera: str = ""
    nivel: str = ""
    modalidad: str = ""
    unidad_organizacion: str = ""
    periodo_academico: str = ""
    creditos: int | None = None
    horas_contacto: int = 0
    horas_practicas: int = 0
    horas_autonomas: int = 0
    total_horas: int = 0
    prerrequisitos: list[str] = []
    correquisitos: list[str] = []
    docente: str = ""
    correo_docente: str = ""


class EjeDeclarado(BaseModel):
    eje: str = Field(description="Denominación exacta de uno de los siete ejes del Modelo Educativo.")
    justificacion: str = Field(
        description="Actividad o evidencia concreta del PF en que se materializa el eje."
    )


class AnclajeCurricular(BaseModel):
    """7.2 Anclaje curricular y contribución al perfil de egreso."""

    competencia_especifica: str = Field(
        "", description="Competencia del perfil de egreso, transcrita sin modificar."
    )
    desempeno_central: str = Field(
        "", description="Verbo de actuación + proceso profesional + finalidad/valor + entorno."
    )
    metacompetencia: str = Field("", description="Una de las cinco metacompetencias institucionales.")
    metacompetencia_secundaria: str | None = None
    habilidades_blandas: list[str] = Field(
        [], description="Al menos una, solo si será ejercitada y evaluada."
    )
    ejes: list[EjeDeclarado] = []
    accesibilidad_nee: str = Field(
        "", description="Cómo el PF es incluyente frente a necesidades educativas específicas."
    )
    articulacion_pf: str = Field(
        "", description="Secuencialidad, integración o complementariedad con otros PF."
    )
    pis_periodo: str | None = None
    aporte_pis: str | None = Field(
        None, description="RA y producto/evidencia que el PF aporta al PIS, sin horas adicionales."
    )
    microcredencial: str | None = None


class ProblemaReto(BaseModel):
    """7.3 Problema del territorio, reto y producto integrador."""

    problema: str = Field(
        "", description="Necesidad documentada + respuesta insuficiente + actores/contexto."
    )
    pregunta_reto: str = Field(
        "", description="¿Cómo podemos + acción + objeto o situación + contexto + beneficio?"
    )
    producto_integrador: str = Field(
        "", description="Producto verificable que se construye progresivamente."
    )
    escenario_actores: str = ""
    criterio_impacto: str = ""


class ResultadoAprendizaje(BaseModel):
    codigo: str = Field(description="RA1, RA2, RA3 o RA4.")
    enunciado: str = Field(description="Resultado oficial de la malla, transcrito sin cambios.")
    evidencia: str = Field("", description="Evidencia observable vinculada al producto integrador.")
    momentos: list[int] = Field([], description="Números de los momentos en que se desarrolla.")


class ResultadosAprendizaje(BaseModel):
    """7.4 Resultados de aprendizaje y evidencias."""

    resultados: list[ResultadoAprendizaje] = []


class Contenidos(BaseModel):
    """7.5 Contenidos: los mínimos oficiales primero, luego su organización."""

    contenidos_minimos: list[str] = []
    conceptuales: list[str] = Field([], description="Saber conocer.")
    procedimentales: list[str] = Field([], description="Saber hacer.")
    actitudinales: list[str] = Field([], description="Saber ser y convivir.")


class EvaluacionMomento(BaseModel):
    evidencia: str = ""
    peso: int = 0
    tipos: list[str] = Field([], description="heteroevaluacion, coevaluacion o autoevaluacion.")
    instrumento: str = ""


class Momento(BaseModel):
    numero: int
    nombre: str = ""
    semanas: str = ""
    ra: list[str] = []
    proposito: str = ""
    contacto_docente: str = ""
    aprendizaje_autonomo: str = ""
    practico_experimental: str = ""
    evidencia_parcial: str = ""
    contenidos_conceptuales: list[str] = []
    contenidos_procedimentales: list[str] = []
    contenidos_actitudinales: list[str] = []
    politica_ia: str = Field(
        "", description="Herramienta + propósito + verificación + transparencia + datos, o «No aplica»."
    )
    horas_contacto: int = 0
    horas_practicas: int = 0
    horas_autonomas: int = 0
    evaluacion: EvaluacionMomento = EvaluacionMomento()
    retroalimentacion: str = ""
    recursos: str = ""


class PlaneacionMomentos(BaseModel):
    """7.6 Planeación operativa por momentos."""

    momentos: list[Momento] = []


class EvidenciaEvaluada(BaseModel):
    momento: int
    ra: list[str] = []
    evidencia: str = ""
    criterios: list[str] = Field([], description="Entre 2 y 4 criterios observables.")
    peso: int = 0
    instrumento: str = "Rúbrica socioformativa"
    oportunidad_mejora: str = ""


class EvaluacionSocioformativa(BaseModel):
    """7.7 Sistema de evaluación socioformativa. Los cinco niveles son fijos (catálogo)."""

    evidencias: list[EvidenciaEvaluada] = []


class RecursosBibliografia(BaseModel):
    """7.8 Recursos, bibliografía y escenarios."""

    bibliografia_basica: list[str] = []
    bibliografia_complementaria: list[str] = []
    bases_datos: list[str] = []
    tecnologia_ia: str = ""
    escenarios: str = ""
    accesibilidad: str = ""


class SeguimientoMejora(BaseModel):
    """Sección 9 de la arquitectura recomendada: seguimiento, mejora y aseguramiento."""

    registro_logro_ra: str = ""
    acciones_mejora: str = ""
    ajustes_siguiente_periodo: str = ""
    cambios_a_escalar: str = Field(
        "", description="Cambios que afectan al currículo y deben escalarse al Comité Curricular."
    )


ESQUEMAS: dict[str, type[BaseModel]] = {
    "identificacion": Identificacion,
    "anclaje_curricular": AnclajeCurricular,
    "problema_reto": ProblemaReto,
    "resultados_aprendizaje": ResultadosAprendizaje,
    "contenidos": Contenidos,
    "planeacion_momentos": PlaneacionMomentos,
    "evaluacion": EvaluacionSocioformativa,
    "recursos": RecursosBibliografia,
    "seguimiento_mejora": SeguimientoMejora,
}


def validar_contenido(clave: str, contenido: dict) -> BaseModel:
    return ESQUEMAS[clave].model_validate(contenido)


def contenido_vacio(clave: str) -> dict:
    return ESQUEMAS[clave]().model_dump(mode="json")
