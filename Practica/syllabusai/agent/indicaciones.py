"""Lo que el docente quiere: preferencias del sílabo e interpretación de sus indicaciones.

El docente orienta al agente de dos maneras: con las preferencias del formulario inicial
(producto, metodología, trabajo en equipo, tecnologías, política de IA, evaluación, bibliografía
propia…) y con indicaciones en lenguaje natural durante la revisión («que trabajen en equipos de
3 y prohíbe la IA en el momento 1»). Este módulo convierte esas indicaciones en cambios
concretos sobre las preferencias, que el agente **recuerda** para el resto del sílabo, y en
ajustes locales de la sección en curso (énfasis, extensión, criterios).

La interpretación es determinista y se hace antes de llamar al modelo: el modelo simulado
trabaja sobre el resultado, y el modelo real (Qwen3-8B) recibe tanto el resultado como el texto
original, de modo que puede atender también lo que estas reglas no reconocen.

Los datos curriculares oficiales (RA, contenidos mínimos, horas, competencia del perfil) no son
preferencias: si el docente pide cambiarlos, el agente lo rechaza y explica a quién escalarlo.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from syllabusai.formato.catalogos import EJES, HABILIDADES_BLANDAS, METACOMPETENCIAS, MOMENTOS

TipoEvaluacion = Literal["heteroevaluacion", "coevaluacion", "autoevaluacion"]
PoliticaIA = Literal["permitida", "limitada", "prohibida"]


class Preferencias(BaseModel):
    """Decisiones del docente que el agente respeta en todas las secciones."""

    tema: str | None = None  # asunto del reto («la gestión de residuos sólidos»)
    producto: str | None = None  # qué construyen los estudiantes
    escenario: str | None = None
    actores: str | None = None
    metodologia: list[str] = []
    trabajo: str | None = None  # «individual», «parejas», «equipos de 3»
    tecnologias: list[str] = []
    politica_ia: PoliticaIA | None = None
    tipos_evaluacion: list[TipoEvaluacion] = []
    instrumento: str | None = None
    habilidades_blandas: list[str] = []
    metacompetencia: str | None = None
    ejes: list[str] = []
    # Peso de evaluación que el docente fija a un momento: {"3": 30}. El resto se reparte.
    pesos: dict[str, int] = {}
    bibliografia: list[str] = []  # referencias que aporta el docente (sí pueden citarse)


# Secciones a las que afecta cada preferencia (para avisar qué se aplica ahora y qué después).
SECCIONES_DE = {
    "tema": ["anclaje_curricular", "problema_reto", "resultados_aprendizaje", "planeacion_momentos"],
    "producto": ["anclaje_curricular", "problema_reto", "resultados_aprendizaje",
                 "planeacion_momentos"],
    "escenario": ["anclaje_curricular", "problema_reto", "planeacion_momentos", "recursos"],
    "actores": ["problema_reto"],
    "metodologia": ["planeacion_momentos"],
    "trabajo": ["planeacion_momentos", "evaluacion"],
    "tecnologias": ["anclaje_curricular", "problema_reto", "contenidos", "planeacion_momentos",
                    "recursos"],
    "politica_ia": ["planeacion_momentos", "evaluacion", "recursos"],
    "tipos_evaluacion": ["planeacion_momentos"],
    "instrumento": ["planeacion_momentos", "evaluacion"],
    "habilidades_blandas": ["anclaje_curricular"],
    "metacompetencia": ["anclaje_curricular"],
    "ejes": ["anclaje_curricular"],
    "pesos": ["planeacion_momentos", "evaluacion"],
    "bibliografia": ["recursos"],
    "problema": ["problema_reto"],  # contexto y fuentes del problema (datos generales)
}

ETIQUETAS = {
    "problema": "problema del territorio",
    "tema": "tema del reto", "producto": "producto integrador", "escenario": "escenario",
    "actores": "actores", "metodologia": "metodología", "trabajo": "modalidad de trabajo",
    "tecnologias": "tecnologías", "politica_ia": "política de uso de IA",
    "tipos_evaluacion": "tipos de evaluación", "instrumento": "instrumento de evaluación",
    "habilidades_blandas": "habilidades blandas", "metacompetencia": "metacompetencia",
    "ejes": "ejes del Modelo Educativo", "pesos": "pesos de evaluación",
    "bibliografia": "bibliografía del docente",
}


@dataclass
class Interpretacion:
    """Resultado de leer una indicación del docente."""

    cambios: dict = field(default_factory=dict)  # campo de Preferencias -> valor nuevo
    quitar: dict = field(default_factory=dict)  # campo de lista -> elementos que se retiran
    datos: dict = field(default_factory=dict)  # datos generales: contexto_problema, fuentes_problema
    enfasis: str | None = None  # solo para la sección en curso
    extension: Literal["breve", "detallada"] | None = None
    criterios: list[str] = field(default_factory=list)
    entendido: list[str] = field(default_factory=list)  # frases legibles para el docente
    rechazado: list[str] = field(default_factory=list)  # pedidos que el agente no puede hacer
    no_entendido: list[str] = field(default_factory=list)

    @property
    def vacia(self) -> bool:
        return not (self.cambios or self.quitar or self.datos or self.enfasis or self.extension
                    or self.criterios or self.rechazado)

    @property
    def campos(self) -> set[str]:
        return set(self.cambios) | set(self.quitar) | ({"problema"} if self.datos else set())

    def local(self) -> dict:
        return {"enfasis": self.enfasis, "extension": self.extension, "criterios": self.criterios}


# --- normalización que conserva posiciones ------------------------------------------------

def _plano(texto: str) -> str:
    """Minúsculas sin tildes, carácter por carácter, para que los índices sigan valiendo."""
    salida = []
    for c in texto:
        base = unicodedata.normalize("NFKD", c.casefold())
        base = "".join(x for x in base if not unicodedata.combining(x))
        salida.append(base[:1] if base else c)
    return "".join(salida)


def _limpiar_valor(texto: str) -> str:
    valor = texto.strip(" .,:;«»\"'")
    return valor[:1].upper() + valor[1:] if valor else valor


# --- vocabulario reconocido ---------------------------------------------------------------

TECNOLOGIAS = {
    r"python": "Python", r"java": "Java", r"javascript|js": "JavaScript",
    r"typescript": "TypeScript", r"c#|c sharp": "C#", r"c\+\+": "C++", r"php": "PHP",
    r"kotlin": "Kotlin", r"swift": "Swift", r"sql": "SQL", r"postgres(ql)?": "PostgreSQL",
    r"mysql": "MySQL", r"sql server": "SQL Server", r"oracle": "Oracle", r"mongo(db)?": "MongoDB",
    r"sqlite": "SQLite", r"tensorflow": "TensorFlow", r"pytorch": "PyTorch", r"keras": "Keras",
    r"scikit[- ]?learn|sklearn": "scikit-learn", r"pandas": "pandas", r"numpy": "NumPy",
    r"jupyter": "Jupyter", r"(google )?colab": "Google Colab", r"power ?bi": "Power BI",
    r"excel": "Excel", r"tableau": "Tableau", r"react": "React", r"angular": "Angular",
    r"vue": "Vue", r"node(\.?js)?": "Node.js", r"django": "Django", r"flask": "Flask",
    r"fastapi": "FastAPI", r"spring( boot)?": "Spring Boot", r"laravel": "Laravel",
    r"flutter": "Flutter", r"android( studio)?": "Android Studio", r"git": "Git",
    r"github": "GitHub", r"gitlab": "GitLab", r"docker": "Docker", r"kubernetes": "Kubernetes",
    r"aws": "AWS", r"azure": "Azure", r"arduino": "Arduino", r"raspberry( pi)?": "Raspberry Pi",
    r"figma": "Figma", r"jira": "Jira", r"trello": "Trello", r"packet tracer": "Cisco Packet Tracer",
    r"gns3": "GNS3", r"wireshark": "Wireshark", r"linux": "Linux", r"langchain": "LangChain",
    r"hugging ?face": "Hugging Face", r"ollama": "Ollama", r"n8n": "n8n",
}

METODOLOGIAS = {
    r"aprendizaje basado en proyectos|\babp\b": "Aprendizaje basado en proyectos (ABP)",
    r"aprendizaje basado en retos": "Aprendizaje basado en retos",
    r"aprendizaje basado en problemas": "Aprendizaje basado en problemas",
    r"aula invertida|flipped( classroom)?|clase invertida": "Aula invertida",
    r"design thinking|pensamiento de diseno": "Design Thinking",
    r"scrum": "Scrum", r"kanban": "Kanban", r"gamificacion|gamificad\w*": "Gamificación",
    r"estudios? de casos?|casos de estudio|metodo de casos": "Estudio de casos",
    r"aprendizaje[- ]servicio": "Aprendizaje-servicio",
    r"hackat[h]?on": "Hackathon", r"seminario": "Seminario", r"taller(es)?": "Talleres prácticos",
}

HABILIDADES = {
    r"comunicacion": "Comunicación efectiva",
    r"trabajo (colaborativo|en equipo)|colaboracion": "Trabajo colaborativo",
    r"liderazgo": "Liderazgo", r"adaptabilidad": "Adaptabilidad", r"empatia": "Empatía",
    r"autorregulacion": "Autorregulación", r"pensamiento critico": "Pensamiento crítico",
    r"resolucion de problemas": "Resolución de problemas",
}
assert set(HABILIDADES.values()) <= set(HABILIDADES_BLANDAS)

METACOMPETENCIA_CLAVES = (
    (r"sociocritic|sistemic|decisiones estrategicas", 0),
    (r"gobernanza|etica digital|etica de la ia", 1),
    (r"innovacion|emprend", 2),
    (r"metacognicion|proyecto etico de vida", 3),
    (r"liderazgo|intercultural|transformacion territorial", 4),
)

EJE_CLAVES = (
    (r"inclusi|desarrollo humano|formacion integral", 0),
    (r"territori|emprendimiento disruptivo", 1),
    (r"complej|interdisciplin", 2),
    (r"intercultur|internacionaliz|justicia cognitiva", 3),
    (r"transformacion digital|inteligencia artificial|\bia\b|gobernanza", 4),
    (r"evaluacion socioformativa|basada en evidencias", 5),
    (r"ecosistema|experiencia universitaria", 6),
)

INSTRUMENTOS = {
    r"lista de cotejo|checklist": "Lista de cotejo",
    r"escala de (valoracion|estimacion)": "Escala de valoración",
    r"rubrica analitica": "Rúbrica analítica",
    r"portafolio": "Portafolio de evidencias",
    r"rubrica": "Rúbrica socioformativa",
}

NUMEROS = {"un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6}

_IA = r"(la )?(ia|i\.a\.|inteligencia artificial|chat ?gpt|asistentes de ia|herramientas de ia)"

# Lo que el sílabo no puede cambiar (Propuesta 2026: IMPORTAR y bloquear).
_OFICIAL = re.compile(
    r"(cambi|modific|reescrib|redact|elimin|quit|borr|reduc|aument|sub|baj)\w*\s+"
    r"(el |la |los |las |un |una )?(numero de )?"
    r"(ra\s?\d|resultados? de aprendizaje|contenidos? minimos?|horas|creditos|competencia especifica"
    r"|prerrequisitos?)"
)

# Conectores que separan dos pedidos dentro de una misma oración.
_VERBOS_PEDIDO = (
    r"usa|usen|utiliza|utilicen|trabaj|agrega|anade|incluye|incorpora|prohib|permit|quita|"
    r"elimina|cambia|pon|evalu|enfoca|enfatiza|prioriza|que|sin|momento|el (problema|producto|reto)"
)
_SEPARADOR = re.compile(rf"[\n;]|\.(?=\s|$)|,\s*(?=y\s)|\s+y\s+(?=({_VERBOS_PEDIDO})\b)")


def _clausulas(texto: str) -> list[tuple[str, str]]:
    """Divide la indicación en pedidos; devuelve pares (original, plano) con el mismo largo."""
    plano = _plano(texto)
    partes, inicio = [], 0
    for m in _SEPARADOR.finditer(plano):
        partes.append((texto[inicio:m.start()], plano[inicio:m.start()]))
        inicio = m.end()
    partes.append((texto[inicio:], plano[inicio:]))
    return [(o.strip(" ,"), p.strip(" ,")) for o, p in partes if p.strip(" ,y")]


def _articulo(palabra: str) -> str:
    if palabra.endswith("os"):
        return "los"
    if palabra.endswith("as"):
        return "las"
    if palabra.endswith(("a", "cion", "sion", "dad", "tad")):
        return "la"
    return "el"


def _valor_tras(original: str, plano: str, patron: str) -> str | None:
    m = re.search(patron, plano)
    if not m or not m.group("v").strip(" .,:;"):
        return None
    return _limpiar_valor(original[m.start("v"):m.end("v")])


# --- interpretación -------------------------------------------------------------------------

def interpretar(texto: str | None) -> Interpretacion:
    r = Interpretacion()
    if not texto or not texto.strip():
        return r

    # Lo que puede contener puntos (referencias, criterios, la descripción del problema con sus
    # datos) se extrae hasta el final de la línea antes de dividir en pedidos.
    patron_ref = (r"(agrega|anade|incluye|incorpora|usa)\w*\s+(tambien\s+)?(la |el |esta |este |mi |"
                  r"como )?(referencia|bibliografia|libro|texto|lectura)s?( de| basica)?\s*:?\s*(?P<v>[^\n]+)")
    extracciones = (
        (patron_ref, "bibliografia"),
        ((r"(agrega|anade|incluye|incorpora)\w*\s+(el |un |este |como )?criterio"
          r"( de evaluacion| de desempeno)?\s*:?\s*(?P<v>[^\n]+)"), "criterio"),
        (r"\(?\bfuentes?( del problema| de los datos)?\s*:\s*(?P<v>[^\n)]+)\)?", "fuentes_problema"),
        (r"\b(el )?problema( del territorio| del contexto)?\s*(es|:)\s+(?P<v>[^\n]+)", "contexto_problema"),
    )
    restante = texto
    for patron, destino in extracciones:
        m = re.search(patron, _plano(restante))
        if not m:
            continue
        valor = restante[m.start("v"):m.end("v")].strip(" «»\"'\n")
        if destino == "bibliografia":
            r.cambios.setdefault("bibliografia", []).append(valor)
            r.entendido.append(f"agregar a la bibliografía «{valor}»")
        elif destino == "criterio":
            criterio = _limpiar_valor(valor)
            r.criterios.append(criterio)
            r.entendido.append(f"agregar el criterio «{criterio}»")
        else:
            valor = valor.replace("()", "").strip()
            if destino == "contexto_problema":
                if _plano(valor).startswith("que "):
                    valor = valor[4:]  # «El problema es que el 40 %…» -> «El 40 %…»
                # Lo que sigue a la descripción en la misma línea puede ser otro pedido
                # («… (fuente: …). Prohíbe la IA.»): esas frases vuelven a interpretarse.
                frases = re.split(r"(?<=[.!?])\s+", valor)
                for i in range(1, len(frases)):
                    if _interpretar_clausula(Interpretacion(), frases[i], _plano(frases[i])):
                        valor, otros = " ".join(frases[:i]), " ".join(frases[i:])
                        restante = restante[:m.end()] + "\n" + otros + restante[m.end():]
                        break
            r.datos[destino] = _limpiar_valor(valor)
            r.entendido.append("registrar " + ("las fuentes del problema" if destino == "fuentes_problema"
                                               else "la descripción del problema del territorio"))
        restante = restante[:m.start()] + restante[m.end():]

    for original, plano in _clausulas(restante):
        if not _interpretar_clausula(r, original, plano):
            r.no_entendido.append(original)
    return r


def _interpretar_clausula(r: Interpretacion, original: str, p: str) -> bool:
    entendio = False

    def anotar(texto: str) -> None:
        nonlocal entendio
        entendio = True
        r.entendido.append(texto)

    if _OFICIAL.search(p):
        r.rechazado.append(
            f"«{original}»: los RA, los contenidos mínimos, las horas, los créditos, la competencia "
            "del perfil y los prerrequisitos son datos oficiales de la malla; no se modifican en el "
            "sílabo. Si hace falta cambiarlos, escálelo al Comité Curricular."
        )
        return True

    # Modalidad de trabajo.
    if m := re.search(r"\b(equipos?|grupos?) de (\d+|" + "|".join(NUMEROS) + r")\b", p):
        n = m.group(2)
        n = int(n) if n.isdigit() else NUMEROS[n]
        r.cambios["trabajo"] = f"equipos de {n}"
        anotar(f"trabajo en equipos de {n} estudiantes")
    elif re.search(r"\b(en )?parejas?\b|\bduplas?\b|\bbinas?\b", p):
        r.cambios["trabajo"] = "parejas"
        anotar("trabajo en parejas")
    elif re.search(r"\bindividual(es|mente)?\b", p) and not re.search(r"habilidad", p):
        r.cambios["trabajo"] = "individual"
        anotar("trabajo individual")

    # Política de IA.
    if re.search(rf"\bsin (usar |uso de |utilizar )?{_IA}\b|\bprohib\w*( el uso de| usar)? {_IA}\b"
                 rf"|\bno (se )?(permit|pued|deb|us|utiliz)\w*( usar| utilizar| el uso de)? {_IA}\b", p):
        r.cambios["politica_ia"] = "prohibida"
        anotar("no permitir el uso de IA")
    elif re.search(rf"\blimit\w*( el uso de)? {_IA}|{_IA}\b.*\b(solo|unicamente|limitad)", p):
        r.cambios["politica_ia"] = "limitada"
        anotar("limitar la IA a explorar alternativas, con verificación")
    elif re.search(rf"\bpermit\w*( el uso de| usar)? {_IA}|{_IA} (permitida|libre)|\bpued\w* usar {_IA}"
                   rf"|\busen {_IA}", p):
        r.cambios["politica_ia"] = "permitida"
        anotar("permitir la IA con declaración de uso")

    # Tipos e instrumentos de evaluación.
    for tipo in ("coevaluacion", "autoevaluacion", "heteroevaluacion"):
        if tipo in p.replace("-", ""):
            if re.search(rf"(sin|quita\w*|elimina\w*|no (incluy|us|hag)\w*)( la)? {tipo}", p.replace("-", "")):
                r.quitar.setdefault("tipos_evaluacion", []).append(tipo)
                anotar(f"retirar la {tipo}")
            else:
                r.cambios.setdefault("tipos_evaluacion", []).append(tipo)
                anotar(f"incluir {tipo}")
    for patron, nombre in INSTRUMENTOS.items():
        if re.search(patron, p) and re.search(r"evalu|instrumento|usa|con|mediante|rubrica|lista|escala", p):
            r.cambios["instrumento"] = nombre
            anotar(f"evaluar con {nombre.lower()}")
            break

    # Pesos por momento: «momento 3 con 30 %».
    for m in re.finditer(r"momento (\d)\D{0,30}?(\d{1,3}) ?(%|por ?ciento|puntos)", p):
        r.cambios.setdefault("pesos", {})[m.group(1)] = int(m.group(2))
        anotar(f"peso del momento {m.group(1)}: {m.group(2)} %")

    # Metodologías, tecnologías, habilidades, metacompetencia, ejes.
    for patron, nombre in METODOLOGIAS.items():
        if re.search(patron, p):
            r.cambios.setdefault("metodologia", []).append(nombre)
            anotar(f"metodología: {nombre}")
    retirar = re.search(r"\b(sin|quita\w*|elimina\w*|no us\w*|no utilic\w*)\b", p)
    for patron, nombre in TECNOLOGIAS.items():
        if re.search(rf"(?<![\w.+#-])({patron})(?![\w+#-])", p):
            if retirar:
                r.quitar.setdefault("tecnologias", []).append(nombre)
                anotar(f"no usar {nombre}")
            else:
                r.cambios.setdefault("tecnologias", []).append(nombre)
                anotar(f"usar {nombre}")
    if re.search(r"habilidad|blanda|soft|fortalec|potenci|ejercit|desarroll\w* (la|el) ", p):
        for patron, nombre in HABILIDADES.items():
            if re.search(patron, p):
                r.cambios.setdefault("habilidades_blandas", []).append(nombre)
                anotar(f"habilidad blanda: {nombre}")
    if "metacompetencia" in p:
        for patron, i in METACOMPETENCIA_CLAVES:
            if re.search(patron, p):
                r.cambios["metacompetencia"] = METACOMPETENCIAS[i]
                anotar(f"metacompetencia: {METACOMPETENCIAS[i]}")
                break
    if re.search(r"\bejes?\b", p):
        for patron, i in EJE_CLAVES:
            if re.search(patron, p):
                r.cambios.setdefault("ejes", []).append(EJES[i])
                anotar(f"eje: {EJES[i]}")

    # Producto, tema, escenario y actores (texto libre del docente).
    producto = _valor_tras(original, p, r"producto( integrador| final)?\s*(debe ser|sera|sea|es|consiste en|:)"
                                        r"\s*(?P<v>.+)") or _valor_tras(
        original, p, r"\b(que )?(los estudiantes |ellos )?(construyan|desarrollen|elaboren|creen|"
                     r"disenen|implementen|programen|hagan|entreguen)\s+(?P<v>.+)")
    if producto:
        r.cambios["producto"] = producto
        anotar(f"producto integrador: {producto}")
    tema = _valor_tras(original, p, r"(reto|problema|proyecto|tema)\w*\s+(debe |deberia )?(tratar |ser |estar )?"
                                    r"(sobre|acerca de|relacionad[oa] con|enfocad[oa] en|centrad[oa] en"
                                    r"|de|:)\s+(?P<v>.+)")
    if tema and not producto:
        r.cambios["tema"] = tema
        anotar(f"tema del reto: {tema}")
    escenario = _valor_tras(original, p, r"(escenario|contexto|lugar)( de aplicacion)?\s*(sera|es|debe ser|:|en)"
                                         r"\s*(?P<v>.+)")
    if not escenario and not (producto or tema):
        escenario = _valor_tras(original, p, r"\ben (?P<v>(la |el |una |un )?(empresa|escuela|unidad educativa|"
                                             r"colegio|hospital|centro de salud|municipio|gad|comunidad|"
                                             r"cooperativa|biblioteca|parroquia|barrio|ciudad|canton|"
                                             r"provincia|fundacion|ong|pyme|mercado)\b.*)")
    if escenario:
        r.cambios["escenario"] = escenario
        anotar(f"escenario: {escenario}")
    actores = _valor_tras(original, p, r"(actores|beneficiarios|usuarios)( principales)?\s*(son|seran|:)\s*(?P<v>.+)")
    if actores:
        r.cambios["actores"] = actores
        anotar(f"actores: {actores}")

    # Ajustes locales de la sección en curso.
    if re.search(r"mas (breve|corto|conciso|resumido|sencillo)|resum[ei]\w*|acorta\w*|menos texto", p):
        r.extension = "breve"
        anotar("redacción más breve")
    elif re.search(r"mas (detallad|extens|ampli|complet|profund)\w*|amplia\w*|detalla\w*|profundiza\w*", p):
        r.extension = "detallada"
        anotar("redacción más detallada")
    enfasis = _valor_tras(original, p, r"(mas |mayor )?(enfasis|enfoque|peso|atencion) (en|a)\s+(?P<v>.+)") or \
        _valor_tras(original, p, r"(enfoca|enfatiza|prioriza|centra)\w*( mas)?( en| a)?\s+(?P<v>.+)")
    if not enfasis and not entendio:
        enfasis = _valor_tras(original, p, r"^(con )?mas (?P<v>[a-z]+( [a-z]+){0,2})$")
        if enfasis:  # «más práctica» -> «la práctica»
            enfasis = f"{_articulo(_plano(enfasis.split()[0]))} {enfasis[0].lower()}{enfasis[1:]}"
    if enfasis and not (producto or tema):
        r.enfasis = enfasis[0].lower() + enfasis[1:]
        anotar(f"énfasis en {r.enfasis}")
    return entendio


# --- memoria de preferencias ----------------------------------------------------------------

LISTAS = ("metodologia", "tecnologias", "tipos_evaluacion", "habilidades_blandas", "ejes",
          "bibliografia")


def fusionar(actuales: dict | None, interpretacion: Interpretacion) -> dict:
    """Aplica la interpretación sobre las preferencias guardadas y devuelve las nuevas."""
    prefs = Preferencias.model_validate(actuales or {}).model_dump()
    for campo, valor in interpretacion.cambios.items():
        if campo in LISTAS:
            prefs[campo] = list(dict.fromkeys(prefs[campo] + list(valor)))
        elif campo == "pesos":
            prefs["pesos"] = prefs["pesos"] | valor
        else:
            prefs[campo] = valor
    for campo, valores in interpretacion.quitar.items():
        prefs[campo] = [v for v in prefs[campo] if v not in valores]
    return Preferencias.model_validate(prefs).model_dump(mode="json")


def preferencias_de(datos_generales: dict) -> Preferencias:
    return Preferencias.model_validate(datos_generales.get("preferencias") or {})


def resumen(prefs: Preferencias) -> list[str]:
    """Frases legibles con lo que el agente tiene en cuenta (para la interfaz y las notas)."""
    lineas = []
    for campo, etiqueta in ETIQUETAS.items():
        valor = getattr(prefs, campo, None)
        if not valor:
            continue
        if campo == "pesos":
            valor = ", ".join(f"momento {k}: {v} %" for k, v in sorted(valor.items()))
        elif isinstance(valor, list):
            valor = "; ".join(valor)
        lineas.append(f"{etiqueta}: {valor}")
    return lineas


# --- pesos de evaluación --------------------------------------------------------------------

def pesos_momentos(fijados: dict[str, int]) -> tuple[list[int], str | None]:
    """Pesos de los cuatro momentos respetando los que fijó el docente.

    Los momentos no fijados se reparten lo que falta hasta 100 % en proporción a los pesos
    sugeridos. Si lo pedido es imposible (más de 100 % o los cuatro fijados sin sumar 100),
    se usan los sugeridos y se devuelve el motivo.
    """
    sugeridos = [m.peso_sugerido for m in MOMENTOS]
    if not fijados:
        return sugeridos, None
    fijos = {int(k): int(v) for k, v in fijados.items() if str(k).isdigit() and 1 <= int(k) <= len(MOMENTOS)}
    resto = 100 - sum(fijos.values())
    libres = [m.numero for m in MOMENTOS if m.numero not in fijos]
    if resto < 0 or (not libres and resto != 0) or (libres and resto < len(libres)):
        return sugeridos, (f"Los pesos pedidos ({', '.join(f'momento {k}: {v} %' for k, v in sorted(fijos.items()))}) "
                           "no permiten sumar 100 %; se mantienen los sugeridos.")
    base = sum(sugeridos[n - 1] for n in libres)
    crudos = {n: resto * sugeridos[n - 1] / base for n in libres}
    enteros = {n: int(v) for n, v in crudos.items()}
    for n in sorted(libres, key=lambda n: crudos[n] - enteros[n], reverse=True)[: resto - sum(enteros.values())]:
        enteros[n] += 1
    return [fijos.get(m.numero, enteros.get(m.numero, 0)) for m in MOMENTOS], None
