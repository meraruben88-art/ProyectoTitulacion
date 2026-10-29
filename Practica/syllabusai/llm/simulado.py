"""Modelo simulado: generador determinista para desarrollar y probar sin GPU.

No es un modelo de lenguaje. Compone cada sección con plantillas a partir de la ficha
curricular, de los datos y preferencias del docente (producto, modalidad de trabajo,
tecnologías, política de IA, evaluación, bibliografía propia) y de los ajustes que pidió para la
sección (énfasis, extensión, criterios), y cita los fragmentos que recibió. Permite ejercitar el
flujo completo (recuperación, abstención, validación, revisión con indicaciones, exportación) y
sus pruebas sin depender del servidor de la A100.
"""

import json
import time

from syllabusai.formato.catalogos import EJES, METACOMPETENCIAS
from syllabusai.llm.base import RespuestaLLM, SolicitudGeneracion

EVIDENCIAS = (
    "Informe técnico de diagnóstico",
    "Diseño documentado de la solución",
    "Prototipo funcional verificado",
    "Producto integrador con defensa y metacognición",
)

POLITICAS_IA = {
    "prohibida": "No aplica: en este momento no se autoriza el uso de herramientas de IA "
                 "generativa; la evidencia se elabora sin asistencia de IA y la autoría se verifica "
                 "en la presentación oral.",
    "limitada": "Asistentes de IA autorizados solo para explorar alternativas; el estudiante "
                "verifica y contrasta los resultados, declara el uso en la evidencia y no ingresa "
                "datos personales ni institucionales.",
    "permitida": "Asistentes de IA autorizados para generar, depurar y documentar alternativas; el "
                 "estudiante verifica cada resultado, declara la herramienta y el propósito en la "
                 "evidencia y no ingresa datos personales ni institucionales.",
}
TECNOLOGIA_IA = {
    "prohibida": "No se autoriza el uso de herramientas de IA generativa en las evidencias "
                 "evaluadas; el docente puede usarlas para preparar materiales, declarándolo.",
    "limitada": "Asistentes de IA autorizados por la institución, solo para explorar alternativas, "
                "con verificación de resultados y declaración de uso en cada evidencia.",
    "permitida": "Asistentes de IA autorizados por la institución (redacción, programación y "
                 "análisis de datos), con verificación de resultados, declaración de uso en cada "
                 "evidencia y sin ingresar datos personales ni institucionales.",
}


class ClienteSimulado:
    nombre = "simulado"

    def __init__(self, retardo_token_s: float = 0.0):
        # Pausa entre trozos al transmitir en vivo, para que la interfaz muestre el progreso.
        self.retardo_token_s = retardo_token_s

    def generar(self, solicitud: SolicitudGeneracion) -> RespuestaLLM:
        inicio = time.perf_counter()
        ctx = solicitud.contexto
        fragmentos = ctx.get("fragmentos", [])
        generador = getattr(self, f"_{solicitud.clave}")
        contenido, abstencion = generador(ctx)
        datos = {
            "contenido": contenido,
            "fuentes": [f["id"] for f in fragmentos[:2]] if abstencion is None else [],
            "abstencion": abstencion,
            "notas": None,
        }
        texto = json.dumps(datos, ensure_ascii=False)
        ttft = None
        if solicitud.al_token is not None:
            for i in range(0, len(texto), 48):
                if ttft is None:
                    ttft = (time.perf_counter() - inicio) * 1000
                solicitud.al_token(texto[i:i + 48])
                if self.retardo_token_s:
                    time.sleep(self.retardo_token_s)
        palabras_entrada = sum(len(m["content"].split()) for m in solicitud.mensajes)
        latencia = (time.perf_counter() - inicio) * 1000
        return RespuestaLLM(
            datos=datos, texto=texto, latencia_ms=latencia, ttft_ms=ttft or latencia,
            tokens_in=palabras_entrada, tokens_out=len(texto.split()), modelo=self.nombre,
        )

    # --- utilidades de redacción -----------------------------------------------------------

    @staticmethod
    def _prefs(ctx: dict) -> dict:
        return ctx.get("preferencias") or {}

    @staticmethod
    def _local(ctx: dict) -> dict:
        return ctx.get("local") or {}

    @staticmethod
    def _enumerar(valores: list[str]) -> str:
        valores = [v for v in valores if v]
        if len(valores) <= 1:
            return "".join(valores)
        return ", ".join(valores[:-1]) + " y " + valores[-1]

    def _redactar(self, ctx: dict, texto: str, detalle: str = "", enfasis: bool = True) -> str:
        """Aplica a un campo narrativo el énfasis y la extensión que pidió el docente."""
        local = self._local(ctx)
        if enfasis and local.get("enfasis"):
            texto = texto.rstrip(".") + f", con énfasis en {local['enfasis']}."
        if local.get("extension") == "breve":
            return texto.split(". ")[0].rstrip(".") + "."
        if local.get("extension") == "detallada" and detalle:
            return f"{texto} {detalle}"
        return texto

    def _producto(self, ctx: dict) -> str:
        p, nombre = self._prefs(ctx), ctx["asignatura"]["nombre"].lower()
        if p.get("producto"):
            return p["producto"][0].lower() + p["producto"][1:]
        if p.get("tema"):
            return f"una solución de {nombre} para {p['tema'][0].lower() + p['tema'][1:]}"
        return f"una solución de {nombre}"

    def _escenario(self, ctx: dict) -> str:
        p, datos = self._prefs(ctx), ctx["datos_generales"]
        escenario = p.get("escenario") or datos.get("escenario") or "la Universidad Tecnológica Indoamérica"
        return escenario[0].lower() + escenario[1:] if escenario[:3].lower() in ("la ", "el ", "una", "un ") else escenario

    def _trabajo(self, ctx: dict) -> str:
        trabajo = self._prefs(ctx).get("trabajo")
        if trabajo == "individual":
            return "de forma individual"
        if trabajo == "parejas":
            return "en parejas"
        if trabajo:
            return f"en {trabajo} estudiantes" if trabajo[-1].isdigit() else f"en {trabajo}"
        return "en equipos colaborativos"

    def _tecnologias(self, ctx: dict, prefijo: str = " con ") -> str:
        tecnologias = self._prefs(ctx).get("tecnologias") or []
        return f"{prefijo}{self._enumerar(tecnologias)}" if tecnologias else ""

    # --- secciones ------------------------------------------------------------------------

    def _anclaje_curricular(self, ctx: dict) -> tuple[dict, None]:
        a, ficha, p = ctx["asignatura"], ctx["ficha"], self._prefs(ctx)
        pis = ficha.get("pis_periodo") or ctx["datos_generales"].get("pis_periodo")
        ultimo_ra = ficha["resultados_aprendizaje"][-1]["codigo"]
        competencia = ficha.get("competencia_especifica") or next(
            (f["texto"].split("\n")[0] for f in ctx.get("fragmentos", []) if f["tipo"] == "perfil_egreso"),
            "",
        )
        prerrequisitos = ", ".join(a["prerrequisitos"]) or "ninguno declarado"
        correquisitos = ", ".join(ficha.get("correquisitos") or []) or "ninguno declarado"
        finalidad = (f"para atender {p['tema'][0].lower() + p['tema'][1:]}" if p.get("tema")
                     else "para responder a necesidades institucionales y del territorio")
        principal = ficha.get("metacompetencia") or p.get("metacompetencia") or METACOMPETENCIAS[1]
        secundaria = p.get("metacompetencia") if p.get("metacompetencia") not in (None, principal) else None
        ejes = [
            {"eje": EJES[4], "justificacion": "Se concreta en la política de uso de IA de cada "
             "momento y en la verificación del prototipo del momento 3."},
            {"eje": EJES[5], "justificacion": "Se concreta en la rúbrica socioformativa y en la "
             "retroalimentación de cada evidencia parcial."},
        ]
        for eje in p.get("ejes") or []:
            if eje not in {e["eje"] for e in ejes}:
                ejes.append({"eje": eje, "justificacion": f"Se concreta en {self._producto(ctx)} y en "
                             "las evidencias parciales de los momentos 2 y 3."})
        return {
            "competencia_especifica": competencia,
            "desempeno_central": self._redactar(
                ctx,
                f"Desarrolla {self._producto(ctx)}{self._tecnologias(ctx)} mediante procesos "
                f"profesionales verificables, {finalidad} en {self._escenario(ctx)}, con criterios "
                "éticos y de calidad.",
                "El desempeño se demuestra en el producto integrador y en su defensa ante los actores "
                "del escenario.",
            ),
            "metacompetencia": principal,
            "metacompetencia_secundaria": secundaria,
            "habilidades_blandas": p.get("habilidades_blandas") or ["Trabajo colaborativo",
                                                                    "Comunicación efectiva"],
            "ejes": ejes,
            "accesibilidad_nee": self._redactar(
                ctx, "Los materiales se entregan en formatos accesibles, las evidencias admiten "
                "ajustes razonables de tiempo y formato, y los equipos se conforman considerando las "
                "necesidades educativas específicas.", enfasis=False),
            "articulacion_pf": f"Secuencialidad con los prerrequisitos ({prerrequisitos}) y "
                               f"complementariedad con los correquisitos ({correquisitos}).",
            "pis_periodo": pis,
            "aporte_pis": (f"{ultimo_ra} y el producto integrador del PF se integran al PIS del "
                           "periodo dentro de la carga horaria regular, sin horas ni créditos "
                           "adicionales.") if pis else None,
            "microcredencial": ficha.get("microcredencial"),
        }, None

    def _problema_reto(self, ctx: dict) -> tuple[dict, str | None]:
        datos, p = ctx["datos_generales"], self._prefs(ctx)
        contexto = (datos.get("contexto_problema") or "").strip()
        if not contexto:
            return {}, "Falta la descripción del problema del territorio con datos y fuentes."
        escenario = self._escenario(ctx)
        actores = p.get("actores") or datos.get("actores") or "estudiantes, docentes y la comunidad vinculada"
        producto = self._producto(ctx)
        tema = f" en relación con {p['tema'][0].lower() + p['tema'][1:]}" if p.get("tema") else ""
        return {
            "problema": self._redactar(
                ctx, f"{contexto.rstrip('.')}. Sin embargo, la respuesta disponible en {escenario}"
                f"{tema} es insuficiente para atender esa necesidad, lo que afecta a {actores}.",
                "La brecha se precisará con los actores durante el momento 1, a partir de las fuentes "
                "registradas por el docente."),
            "pregunta_reto": f"¿Cómo podemos desarrollar {producto} que atienda la necesidad "
                             f"identificada en {escenario} para mejorar la respuesta a {actores}?",
            "producto_integrador": self._redactar(
                ctx, f"{producto[0].upper() + producto[1:]}{self._tecnologias(ctx, ', desarrollado con ')}, "
                "documentado y verificado, construido de forma progresiva a partir de las evidencias "
                "de cada momento.", enfasis=False),
            "escenario_actores": f"{escenario[0].upper() + escenario[1:]}; actores: {actores}.",
            "criterio_impacto": "La solución es pertinente si resuelve la brecha descrita, se valida "
                                "con los actores del escenario y respeta criterios éticos y de "
                                "protección de datos.",
        }, None

    def _resultados_aprendizaje(self, ctx: dict) -> tuple[dict, None]:
        momentos = ctx.get("momentos_de_ra", {})
        producto = self._producto(ctx) if self._prefs(ctx).get("producto") or self._prefs(ctx).get("tema") else None
        resultados = []
        for i, ra in enumerate(ctx["ficha"]["resultados_aprendizaje"]):
            evidencia = EVIDENCIAS[i % len(EVIDENCIAS)]
            if producto:
                evidencia += f" de {producto}"
            resultados.append({
                "codigo": ra["codigo"],
                "enunciado": ra["enunciado"],
                "evidencia": self._redactar(
                    ctx, f"{evidencia} que demuestra el desempeño del {ra['codigo']} y alimenta el "
                    "producto integrador.", enfasis=False),
                "momentos": momentos.get(ra["codigo"], [4]),
            })
        return {"resultados": resultados}, None

    def _contenidos(self, ctx: dict) -> tuple[dict, None]:
        minimos = ctx["ficha"]["contenidos_minimos"]
        local = self._local(ctx)
        conceptuales = [f"Fundamentos de {c[0].lower() + c[1:]}" for c in minimos]
        procedimentales = [f"Aplicación de {c[0].lower() + c[1:]} en el producto integrador"
                           for c in minimos]
        if self._prefs(ctx).get("tecnologias"):
            procedimentales.append(f"Uso de {self._enumerar(self._prefs(ctx)['tecnologias'])} para "
                                   "implementar y verificar el producto integrador")
        if local.get("enfasis"):
            conceptuales.append(f"Profundización en {local['enfasis']}")
        if local.get("extension") == "breve":
            conceptuales, procedimentales = conceptuales[:3], procedimentales[:3]
        return {
            "contenidos_minimos": list(minimos),
            "conceptuales": conceptuales,
            "procedimentales": procedimentales,
            "actitudinales": ["Responsabilidad y honestidad académica en la autoría del producto",
                              "Colaboración respetuosa en el trabajo en equipo",
                              "Uso ético y transparente de la inteligencia artificial"],
        }, None

    def _planeacion_momentos(self, ctx: dict) -> tuple[dict, None]:
        p = self._prefs(ctx)
        minimos = ctx["ficha"]["contenidos_minimos"]
        evidencias = {r["codigo"]: r.get("evidencia", "")
                      for r in ctx.get("aprobadas", {}).get("resultados_aprendizaje", {}).get("resultados", [])}
        metodologia = self._enumerar(p.get("metodologia") or [])
        contacto = ("Modelado del docente, análisis de casos y retroalimentación del avance del "
                    "producto.")
        if metodologia:
            contacto = f"Sesiones con {metodologia}: " + contacto[0].lower() + contacto[1:]
        tipos = p.get("tipos_evaluacion") or ["heteroevaluacion", "autoevaluacion"]
        instrumento = p.get("instrumento") or "Rúbrica socioformativa"
        politica = POLITICAS_IA[p.get("politica_ia") or "limitada"]
        momentos = []
        for i, base in enumerate(ctx["esqueleto_momentos"]):
            # Los contenidos mínimos se reparten entre los tres primeros momentos.
            propios = [c for j, c in enumerate(minimos) if j % 3 == min(i, 2)] if i < 3 else []
            ultimo = i == len(ctx["esqueleto_momentos"]) - 1
            # El último momento integra todos los RA en el producto integrador final.
            evidencia = EVIDENCIAS[-1] if ultimo else evidencias.get(base["ra"][-1]) or EVIDENCIAS[i]
            momentos.append(base | {
                "proposito": self._redactar(
                    ctx, f"Avanzar {self._producto(ctx)} en la fase de {base['nombre'].lower()}.",
                    "Cada sesión cierra con una verificación del avance frente al RA del momento."),
                "contacto_docente": contacto,
                "aprendizaje_autonomo": "Lectura dirigida, preparación de la evidencia y registro "
                                        "en el portafolio.",
                "practico_experimental": f"Trabajo {self._trabajo(ctx)} en un escenario real o "
                                         f"simulado ({self._escenario(ctx)}){self._tecnologias(ctx)}, "
                                         "con la guía de práctica.",
                "evidencia_parcial": evidencia,
                "contenidos_conceptuales": propios or ["Integración de los contenidos del PF"],
                "contenidos_procedimentales": [f"Ejecución de la fase {base['numero']} del proyecto"],
                "contenidos_actitudinales": ["Trabajo colaborativo y ético"],
                "politica_ia": politica,
                "evaluacion": {"evidencia": evidencia, "peso": base["peso"], "tipos": list(tipos),
                               "instrumento": instrumento},
                "retroalimentacion": "Retroalimentación escrita en la semana siguiente a la "
                                     "entrega, con una oportunidad de mejora.",
                "recursos": "Plataforma institucional, laboratorio y bibliografía básica"
                            + self._tecnologias(ctx, "; software: ") + ".",
            })
        return {"momentos": momentos}, None

    def _evaluacion(self, ctx: dict) -> tuple[dict, None]:
        p, local = self._prefs(ctx), self._local(ctx)
        base = [
            "Pertinencia de la solución respecto del problema y del RA",
            "Fundamentación técnica con fuentes verificables",
            "Autoría demostrada y uso ético declarado de la IA"
            if p.get("politica_ia") != "prohibida" else "Autoría demostrada sin asistencia de IA",
        ]
        if (p.get("trabajo") or "").startswith("equipos") or p.get("trabajo") == "parejas":
            base.insert(1, "Contribución individual verificable dentro del equipo")
        criterios = (list(local.get("criterios") or []) + base)[:4]
        evidencias = []
        for e in ctx["esqueleto_evaluacion"]:
            final = e["momento"] == len(ctx["esqueleto_evaluacion"])
            evidencias.append(e | {
                "criterios": criterios,
                "instrumento": p.get("instrumento") or "Rúbrica socioformativa",
                "oportunidad_mejora": "Hasta 3 reentregas del producto final con retroalimentación."
                if final else "Una reentrega de la evidencia parcial tras la retroalimentación.",
            })
        return {"evidencias": evidencias}, None

    def _recursos(self, ctx: dict) -> tuple[dict, str | None]:
        p = self._prefs(ctx)
        candidatos = ctx.get("candidatos_bibliografia") or []
        if not candidatos:
            return {}, "No hay bibliografía en la ficha ni en los documentos recuperados."
        # Las referencias que aportó el docente van primero en la bibliografía básica.
        propias = [c for c in candidatos if c in (p.get("bibliografia") or [])]
        otras = [c for c in candidatos if c not in propias]
        basica = (propias + otras)[:max(2, len(propias))]
        return {
            "bibliografia_basica": basica,
            "bibliografia_complementaria": [c for c in otras if c not in basica][:2],
            "bases_datos": ["Bases de datos científicas de la biblioteca institucional"],
            "tecnologia_ia": TECNOLOGIA_IA[p.get("politica_ia") or "limitada"],
            "escenarios": self._redactar(
                ctx, f"Laboratorio de computación y {self._escenario(ctx)} como escenario del reto"
                + self._tecnologias(ctx, "; software: ") + "."),
            "accesibilidad": "Materiales en formatos accesibles y ajustes razonables de tiempo y "
                             "formato en las evidencias.",
        }, None

    def _seguimiento_mejora(self, ctx: dict) -> tuple[dict, None]:
        return {
            "registro_logro_ra": "El logro de cada RA se registra por evidencia con el nivel de la "
                                 "rúbrica socioformativa alcanzado por cada estudiante.",
            "acciones_mejora": self._redactar(
                ctx, "Análisis de las evidencias con nivel inferior a Resolutivo y retroalimentación "
                "de estudiantes y actores al cierre de cada momento.",
                "Los resultados se discuten en la reunión de área al cierre del periodo."),
            "ajustes_siguiente_periodo": "Ajuste de actividades, recursos y distribución semanal "
                                         "dentro de los totales oficiales.",
            "cambios_a_escalar": "Cualquier discrepancia en RA, contenidos mínimos, horas o "
                                 "prerrequisitos se reporta al Comité Curricular.",
        }, None
