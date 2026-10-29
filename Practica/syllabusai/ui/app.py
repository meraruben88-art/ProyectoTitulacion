"""Interfaz del docente (Streamlit). Se comunica con la API de SyllabusAI.

    syllabusai api      # en una terminal
    syllabusai ui       # en otra; abre http://localhost:8501

Variable de entorno SYLLABUSAI_API para apuntar a otra dirección de la API.
"""

import json
import os
from typing import Any

import httpx
import streamlit as st

API = os.environ.get("SYLLABUSAI_API", "http://127.0.0.1:8080")

# Datos oficiales que el docente ve pero no edita (Propuesta 2026: IMPORTAR y bloquear).
BLOQUEADOS = {
    "identificacion": {"*"},
    "resultados_aprendizaje": {"codigo", "enunciado"},
    "contenidos": {"contenidos_minimos"},
    "planeacion_momentos": {"numero", "semanas", "ra", "horas_contacto", "horas_practicas",
                            "horas_autonomas", "peso"},
    "evaluacion": {"momento", "ra", "peso"},
}
ETIQUETAS_ESTADO = {"pendiente": "⏳ pendiente", "propuesta": "📝 propuesta",
                    "aprobada": "✅ aprobada", "abstenida": "⚠️ abstenida"}

st.set_page_config(page_title="SyllabusAI", page_icon="📘", layout="wide")


# --- cliente de la API --------------------------------------------------------------------

def api(metodo: str, ruta: str, **kwargs) -> Any:
    cred = st.session_state.get("credenciales")
    try:
        r = httpx.request(metodo, f"{API}{ruta}", auth=cred, timeout=600, **kwargs)
    except httpx.HTTPError as error:
        st.error(f"No se pudo contactar la API en {API}: {error}. ¿Está corriendo `syllabusai api`?")
        st.stop()
    if r.status_code >= 400:
        try:
            detalle = r.json().get("detail")
        except ValueError:
            detalle = r.text
        raise RuntimeError(detalle if isinstance(detalle, str) else json.dumps(detalle, ensure_ascii=False))
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r


def accion(funcion, *args, exito: str | None = None, **kwargs):
    try:
        with st.spinner("Trabajando… (la generación puede tardar)"):
            resultado = funcion(*args, **kwargs)
        if exito:
            st.toast(exito)
        return resultado
    except RuntimeError as error:
        st.error(str(error))
        return None


# --- inicio de sesión ---------------------------------------------------------------------

def pantalla_login() -> None:
    st.title("📘 SyllabusAI")
    st.caption("Agente RAG para la creación asistida de sílabos · Formato UTI 2026")
    with st.form("login"):
        correo = st.text_input("Correo institucional")
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary"):
            st.session_state["credenciales"] = (correo, clave)
            try:
                st.session_state["usuario"] = api("POST", "/auth/login")
                st.rerun()
            except RuntimeError as error:
                st.session_state.pop("credenciales", None)
                st.error(f"No se pudo ingresar: {error}")
    st.info("Principio central: el agente propone y verifica; el docente revisa, corrige y aprueba.")


# --- editor genérico de secciones ---------------------------------------------------------

def editor(valor: Any, clave_seccion: str, ruta: str, prefijo: str, etiqueta: str) -> Any:
    bloqueados = BLOQUEADOS.get(clave_seccion, set())
    campo = ruta.split(".")[-1]
    bloqueado = "*" in bloqueados or campo in bloqueados
    titulo = etiqueta.replace("_", " ").capitalize() + (" 🔒 oficial" if bloqueado else "")
    k = f"{prefijo}:{ruta}"
    if isinstance(valor, dict):
        return {c: editor(v, clave_seccion, f"{ruta}.{c}", prefijo, c) for c, v in valor.items()}
    if isinstance(valor, list) and valor and all(isinstance(x, dict) for x in valor):
        nuevos = []
        for i, item in enumerate(valor):
            nombre = item.get("codigo") or item.get("eje") or (
                f"Momento {item['numero']}" if "numero" in item else
                f"Evidencia del momento {item['momento']}" if "momento" in item else f"{etiqueta} {i + 1}")
            with st.expander(str(nombre)[:90], expanded=False):
                nuevos.append(editor(item, clave_seccion, f"{ruta}.{i}", prefijo, ""))
        return nuevos
    if isinstance(valor, list) or (valor is None and etiqueta in ("prerrequisitos", "correquisitos")):
        texto = st.text_area(titulo, "\n".join(map(str, valor or [])), key=k, disabled=bloqueado,
                             help="Un elemento por línea")
        lineas = [x.strip() for x in texto.splitlines() if x.strip()]
        if valor and all(isinstance(x, int) for x in valor):
            return [int(x) for x in lineas if x.isdigit()]
        return lineas
    if isinstance(valor, bool):
        return st.checkbox(titulo, valor, key=k, disabled=bloqueado)
    if isinstance(valor, int):
        return int(st.number_input(titulo, value=valor, step=1, key=k, disabled=bloqueado))
    texto = st.text_area(titulo, "" if valor is None else str(valor), key=k, disabled=bloqueado,
                         height=90 if len(str(valor or "")) > 120 else 68)
    return texto if texto.strip() or valor is not None else None


def mostrar_hallazgos(hallazgos: list[dict], silabo_id: int, permitir_descartar: bool = True) -> None:
    for h in hallazgos:
        texto = f"**{h['regla']}** · {h['mensaje']}"
        if h["resuelto"]:
            st.caption(f"~~{h['regla']}: {h['mensaje']}~~ (descartada con justificación)")
        elif h["severidad"] == "bloqueante":
            st.error(texto, icon="⛔")
        else:
            st.warning(texto, icon="⚠️")
            if permitir_descartar:
                with st.popover("Descartar advertencia"):
                    just = st.text_input("Justificación", key=f"just-{h['id']}")
                    descartar = st.button("Descartar", key=f"desc-{h['id']}") and just
                    if descartar and accion(
                        api, "POST", f"/silabos/{silabo_id}/hallazgos/{h['id']}/descartar",
                        json={"justificacion": just},
                    ):
                        st.rerun()


def mostrar_fuentes(seccion: dict) -> None:
    if not seccion["citas"]:
        st.caption("Sin fuentes: sección importada de la ficha curricular o en abstención.")
        return
    for cita in seccion["citas"]:
        vigencia = "" if cita["vigente"] else " · ⚠️ documento obsoleto"
        with st.expander(f"📄 {cita['documento']} · v{cita['version']} · p. {cita['pagina']}{vigencia}"):
            st.caption(f"Fragmento {cita['fragmento_id']}")
            st.write(cita["texto"])


SIN_PREFERENCIA = "(sin preferencia)"


def campos_preferencias(actuales: dict, opciones: dict, k: str) -> dict:
    """Widgets de las preferencias del docente; devuelve el diccionario para la API."""
    def elegir(etiqueta, valores, actual, columna, **extra):
        valores = [SIN_PREFERENCIA] + list(valores) + ([actual] if actual and actual not in valores else [])
        valor = columna.selectbox(etiqueta, valores, index=valores.index(actual) if actual else 0,
                                  key=f"{k}-{etiqueta}", **extra)
        return None if valor == SIN_PREFERENCIA else valor

    def varios(etiqueta, valores, actual, columna):
        valores = list(dict.fromkeys(list(valores) + list(actual or [])))
        return columna.multiselect(etiqueta, valores, default=actual or [], key=f"{k}-{etiqueta}")

    producto = st.text_input("¿Qué construirán los estudiantes? (producto integrador)",
                             actuales.get("producto") or "", key=f"{k}-producto",
                             placeholder="p. ej. un asistente conversacional que oriente a los "
                                         "estudiantes nuevos")
    tema = st.text_input("Tema del reto", actuales.get("tema") or "", key=f"{k}-tema",
                         placeholder="p. ej. la deserción estudiantil en primer nivel")
    c1, c2 = st.columns(2)
    preferencias = dict(actuales) | {
        "producto": producto.strip() or None,
        "tema": tema.strip() or None,
        "metodologia": varios("Metodología", opciones["metodologias"], actuales.get("metodologia"), c1),
        "trabajo": elegir("Modalidad de trabajo", ["individual", "parejas", "equipos de 3",
                                                   "equipos de 4", "equipos de 5"],
                          actuales.get("trabajo"), c2),
        "tecnologias": varios("Tecnologías / software", opciones["tecnologias"],
                              actuales.get("tecnologias"), c1),
        "politica_ia": elegir("Uso de IA por los estudiantes", ["permitida", "limitada", "prohibida"],
                              actuales.get("politica_ia"), c2,
                              help="permitida: con declaración de uso · limitada: solo para explorar "
                                   "alternativas · prohibida: «No aplica» en cada momento"),
        "tipos_evaluacion": varios("Tipos de evaluación", ["heteroevaluacion", "coevaluacion",
                                                           "autoevaluacion"],
                                   actuales.get("tipos_evaluacion"), c1),
        "instrumento": elegir("Instrumento de evaluación", opciones["instrumentos"],
                              actuales.get("instrumento"), c2),
        "habilidades_blandas": varios("Habilidades blandas que se ejercitan y evalúan",
                                      opciones["habilidades_blandas"],
                                      actuales.get("habilidades_blandas"), st),
    }
    bibliografia = st.text_area(
        "Bibliografía que usted propone (una referencia por línea)",
        "\n".join(actuales.get("bibliografia") or []), height=68, key=f"{k}-bibliografia",
        help="El agente solo cita referencias de la malla, de los documentos del corpus o las que "
             "usted escriba aquí.")
    preferencias["bibliografia"] = [x.strip() for x in bibliografia.splitlines() if x.strip()]
    return preferencias


def panel_memoria(s: dict) -> None:
    """Barra lateral: lo que el agente recuerda del docente para este sílabo."""
    st.subheader("🧠 Lo que el agente recuerda")
    if s["preferencias"]:
        for linea in s["preferencias"]:
            st.caption("• " + linea)
    else:
        st.caption("Aún no hay preferencias: pídale lo que quiera en la conversación.")
    inicial = s["datos_generales"].get("interpretacion_inicial") or {}
    if inicial.get("no_entendido") or inicial.get("rechazado"):
        with st.expander("De sus indicaciones iniciales"):
            for texto in inicial.get("rechazado", []):
                st.warning(texto)
            for texto in inicial.get("no_entendido", []):
                st.caption(f"No interpretado: «{texto}»")
    with st.popover("✏️ Editar preferencias", width="stretch"), st.form(f"prefs-{s['id']}"):
        nuevas = campos_preferencias(s["datos_generales"].get("preferencias") or {},
                                     api("GET", "/formato"), f"mem-{s['id']}")
        if st.form_submit_button("Guardar", type="primary") and accion(
            api, "PUT", f"/silabos/{s['id']}/preferencias", json=nuevas,
            exito="Preferencias guardadas: rigen desde la próxima propuesta",
        ):
            st.rerun()


def en_vivo(silabo_id: int, clave: str, cuerpo: dict) -> bool:
    """Envía la decisión y muestra en vivo los pasos del agente y el texto del modelo (RNF-07)."""
    texto = ""
    with st.status("El agente está trabajando…", expanded=True) as estado:
        caja = st.empty()
        try:
            with httpx.stream("POST", f"{API}/silabos/{silabo_id}/secciones/{clave}/stream",
                              json=cuerpo, auth=st.session_state.get("credenciales"),
                              timeout=600) as r:
                if r.status_code >= 400:
                    r.read()
                    estado.update(label="No se pudo completar", state="error")
                    st.error(r.json().get("detail", r.text))
                    return False
                for linea in r.iter_lines():
                    if not linea.startswith("data:"):
                        continue
                    evento = json.loads(linea[5:])
                    if evento["tipo"] == "paso":
                        st.write(f"• {evento['texto']}")
                        texto = ""
                    elif evento["tipo"] == "token":
                        texto += evento["texto"]
                        caja.code(texto[-1200:], language="json", wrap_lines=True)
                    elif evento["tipo"] == "error":
                        estado.update(label="Error", state="error")
                        st.error(evento["mensaje"])
                        return False
                    elif evento["tipo"] == "fin":
                        estado.update(label="Listo", state="complete", expanded=False)
        except httpx.HTTPError as error:
            st.error(f"No se pudo contactar la API en {API}: {error}")
            return False
    return True


def conversacion(s: dict, seccion: dict) -> None:
    """Diálogo con el agente sobre la sección: lo pedido en cada versión y lo que respondió."""
    for v in seccion["historial"]:
        if v["origen"] == "docente":
            with st.chat_message("user"):
                st.write(f"✏️ Edité la sección (versión {v['n']}).")
            continue
        if v.get("indicacion"):
            with st.chat_message("user"):
                st.write(v["indicacion"])
        with st.chat_message("assistant"):
            st.write(v.get("nota") or f"Le propongo la versión {v['n']} a partir de la ficha, sus "
                                       "preferencias y la evidencia del corpus.")
    if seccion["tipo"] != "generada":
        st.caption("Esta sección se importa de la ficha curricular: no se redacta con el modelo.")
        return
    pedido = st.chat_input("Pídale al agente un cambio (p. ej. «en equipos de 3 y sin IA»)",
                           key=f"chat-{s['id']}-{seccion['clave']}")
    if pedido and en_vivo(s["id"], seccion["clave"], {"accion": "regenerar", "indicacion": pedido}):
        st.rerun()


# --- pantallas ----------------------------------------------------------------------------

def pantalla_silabos(usuario: dict) -> None:
    st.header("Mis sílabos")
    silabos = api("GET", "/silabos")
    if not silabos:
        st.info("Todavía no hay sílabos. Cree uno en «Nuevo sílabo».")
    for s in silabos:
        c1, c2, c3 = st.columns([5, 2, 1])
        c1.markdown(f"**{s['asignatura']}** · periodo {s['periodo']}")
        c2.progress(s["aprobadas"] / s["secciones"], text=f"{s['estado']} · {s['aprobadas']}/{s['secciones']}")
        if c3.button("Abrir", key=f"abrir-{s['id']}"):
            st.session_state["silabo_id"] = s["id"]
            st.session_state["vista"] = "Revisión"
            st.rerun()


def pantalla_nuevo() -> None:
    st.header("Nuevo sílabo · datos generales")
    asignaturas = api("GET", "/asignaturas")
    if not asignaturas:
        st.warning("No hay asignaturas en el catálogo curricular.")
        return
    opciones = {f"{a['codigo']} · {a['nombre']} (nivel {a['nivel']})": a for a in asignaturas}
    elegida = opciones[st.selectbox("Proyecto Formativo (asignatura)", list(opciones))]
    ficha = elegida["ficha"]
    with st.expander("Datos curriculares que se importarán sin modificación 🔒", expanded=True):
        st.write(f"Horas: contacto {ficha['horas_contacto']} · práctico-experimentales "
                 f"{ficha['horas_practicas']} · autónomas {ficha['horas_autonomas']} · total {elegida['horas']}")
        for ra in ficha["resultados_aprendizaje"]:
            st.markdown(f"- **{ra['codigo']}**: {ra['enunciado']}")
        st.markdown("**Contenidos mínimos:** " + "; ".join(ficha["contenidos_minimos"]))
    opciones_formato = api("GET", "/formato")
    with st.form("nuevo"):
        c1, c2 = st.columns(2)
        periodo = c1.text_input("Periodo académico", "B26")
        semanas = c2.number_input("Semanas del periodo", 8, 24, 16)
        contexto = st.text_area(
            "Problema / necesidad del territorio (con datos)", height=120,
            help="Necesidad documentada + respuesta insuficiente + actores. El agente no inventa "
                 "datos del territorio: sin esta descripción, la sección 7.3 se abstiene (puede "
                 "dársela después, conversando con el agente).")
        fuentes = st.text_area("Fuentes que documentan el problema", height=68)
        c3, c4 = st.columns(2)
        escenario = c3.text_input("Escenario", "la Universidad Tecnológica Indoamérica, sede Quito")
        actores = c4.text_input("Actores del contexto", "estudiantes, docentes y la comunidad vinculada")

        st.markdown("#### ¿Cómo quiere su sílabo?")
        st.caption("Todo es opcional. El agente lo recuerda en todas las secciones y puede cambiarlo "
                   "después, conversando con él o desde el panel «Lo que el agente recuerda».")
        preferencias = campos_preferencias({}, opciones_formato, "nuevo")
        indicaciones = st.text_area(
            "Otras indicaciones para el agente (texto libre)", height=80,
            placeholder="p. ej. «Que trabajen en equipos de 3, momento 3 con 30 %, énfasis en la "
                        "ética de los datos. El reto debe tratar sobre la deserción estudiantil.»")
        if st.form_submit_button("Crear sílabo e iniciar el agente", type="primary"):
            datos = {"semanas_periodo": int(semanas), "contexto_problema": contexto,
                     "fuentes_problema": fuentes, "escenario": escenario, "actores": actores,
                     "preferencias": preferencias, "indicaciones_generales": indicaciones}
            r = accion(api, "POST", "/silabos", json={"asignatura_id": elegida["id"],
                                                      "periodo": periodo, "datos_generales": datos})
            if r:
                st.session_state["silabo_id"] = r["id"]
                st.session_state["vista"] = "Revisión"
                st.rerun()


def pantalla_revision() -> None:
    silabo_id = st.session_state.get("silabo_id")
    if not silabo_id:
        st.info("Abra un sílabo desde «Mis sílabos».")
        return
    s = api("GET", f"/silabos/{silabo_id}")
    pausa = s["pausa"]
    aprobadas = sum(1 for x in s["secciones"] if x["estado"] == "aprobada")
    st.header(f"{s['asignatura']['codigo']} {s['asignatura']['nombre']} · {s['periodo']}")
    st.progress(aprobadas / len(s["secciones"]), text=f"Estado: {s['estado']} · {aprobadas}/{len(s['secciones'])} secciones aprobadas")

    with st.sidebar:
        st.subheader("Secciones")
        for x in s["secciones"]:
            marca = "▶ " if pausa.get("clave") == x["clave"] else ""
            st.write(f"{marca}{ETIQUETAS_ESTADO[x['estado']]} · {x['titulo']}")
        panel_memoria(s)

    if pausa["tipo"] in ("sin_iniciar",) or (pausa["tipo"] == "terminado" and s["estado"] == "borrador"):
        if st.button("Iniciar / retomar el agente", type="primary"):
            accion(api, "POST", f"/silabos/{silabo_id}/continuar")
            st.rerun()
        return

    if pausa["tipo"] == "revision_seccion":
        revisar_seccion(s, pausa)
    elif pausa["tipo"] == "correccion":
        st.subheader("Verificación global: hay hallazgos bloqueantes")
        mostrar_hallazgos([h for h in s["hallazgos"] if not h["resuelto"]], silabo_id)
        claves = sorted({h["seccion"] for h in pausa["hallazgos"] if h["seccion"]})
        c1, c2 = st.columns(2)
        if claves:
            clave = c1.selectbox("Sección a corregir", claves)
            if c1.button("Reabrir sección", type="primary"):
                accion(api, "POST", f"/silabos/{silabo_id}/secciones/{clave}/reabrir")
                st.rerun()
        if c2.button("Volver a verificar"):
            accion(api, "POST", f"/silabos/{silabo_id}/validar")
            st.rerun()
    else:
        pantalla_final(s)


def revisar_seccion(s: dict, pausa: dict) -> None:
    silabo_id = s["id"]
    seccion = next(x for x in s["secciones"] if x["clave"] == pausa["clave"])
    st.subheader(seccion["titulo"])
    st.caption(f"{ETIQUETAS_ESTADO[seccion['estado']]} · versión {seccion['version']} "
               f"({seccion['origen'] or '—'})")
    if pausa.get("error"):
        st.error(pausa["error"])
    propios = [h for h in s["hallazgos"] if h["seccion"] == seccion["clave"]]
    izquierda, derecha = st.columns([3, 2])
    with izquierda:
        prefijo = f"{silabo_id}-{seccion['clave']}-{seccion['version']}"
        modo_json = st.toggle("Editar como JSON", key=f"json-{prefijo}")
        contenido = seccion["contenido"] or {}
        if modo_json:
            texto = st.text_area("Contenido (JSON)", json.dumps(contenido, ensure_ascii=False, indent=2),
                                 height=500, key=f"txt-{prefijo}")
            try:
                editado = json.loads(texto)
            except json.JSONDecodeError as error:
                st.error(f"JSON inválido: {error}")
                editado = contenido
        else:
            editado = editor(contenido, seccion["clave"], "c", prefijo, "")
        cambiado = editado != contenido
        c1, c2 = st.columns(2)
        # Al aprobar, el agente pasa a la sección siguiente y la redacta: se muestra en vivo.
        if c1.button("✅ Aprobar y continuar" + (" con mis cambios" if cambiado else ""), type="primary",
                     disabled=seccion["estado"] == "abstenida" and not cambiado):
            cuerpo = {"accion": "aprobar", "contenido": editado if cambiado else None}
            if en_vivo(silabo_id, seccion["clave"], cuerpo):
                st.toast("Sección aprobada")
                st.rerun()
        if c2.button("💾 Guardar edición", disabled=not cambiado) and accion(
            api, "PUT", f"/silabos/{silabo_id}/secciones/{seccion['clave']}",
            json={"contenido": editado}, exito="Edición guardada y validada",
        ):
            st.rerun()
    with derecha:
        abiertos = [h for h in propios if not h["resuelto"]]
        charla, alertas, fuentes = st.tabs([
            "💬 Conversación con el agente",
            f"⚠️ Alertas ({len(abiertos)})" if abiertos else "✅ Alertas",
            f"📄 Fuentes ({len(seccion['citas'])})",
        ])
        with charla:
            conversacion(s, seccion)
        with alertas:
            if propios:
                mostrar_hallazgos(propios, silabo_id)
            else:
                st.success("Sin hallazgos en esta sección.")
        with fuentes:
            mostrar_fuentes(seccion)


def pantalla_final(s: dict) -> None:
    silabo_id = s["id"]
    st.success("Todas las secciones están aprobadas y sin hallazgos bloqueantes.")
    advertencias = [h for h in s["hallazgos"] if h["severidad"] == "advertencia"]
    if advertencias:
        st.markdown("**Advertencias** (puede descartarlas con una justificación)")
        mostrar_hallazgos(advertencias, silabo_id)
    c1, c2, c3 = st.columns(3)
    for col, formato in ((c1, "docx"), (c2, "pdf")):
        if col.button(f"Generar {formato.upper()}"):
            r = accion(api, "POST", f"/silabos/{silabo_id}/exportar", params={"formato": formato})
            if r is not None:
                st.session_state[f"archivo-{formato}"] = (r.content, r.headers.get("content-disposition", ""))
        if f"archivo-{formato}" in st.session_state:
            contenido, _ = st.session_state[f"archivo-{formato}"]
            col.download_button(f"⬇️ Descargar {formato.upper()}", contenido,
                                file_name=f"silabo_{silabo_id}.{formato}")
    with c3:
        clave = st.selectbox("Reabrir una sección", [x["clave"] for x in s["secciones"]])
        if st.button("Reabrir"):
            accion(api, "POST", f"/silabos/{silabo_id}/secciones/{clave}/reabrir")
            st.rerun()
    with st.expander("Contenido aprobado"):
        for x in s["secciones"]:
            st.markdown(f"**{x['titulo']}**")
            st.json(x["contenido"], expanded=False)


def pantalla_corpus(usuario: dict) -> None:
    st.header("Corpus institucional")
    documentos = api("GET", "/documentos")
    for d in documentos:
        c1, c2, c3 = st.columns([6, 2, 2])
        c1.markdown(f"**{d['titulo']}** · v{d['version']} · {d['tipo']} · {d['carrera']} · "
                    f"{d['fragmentos']} fragmentos")
        c2.write("🟢 vigente" if d["estado"] == "vigente" else "⚪ obsoleto")
        if usuario["rol"] == "admin_corpus":
            nuevo = "obsoleto" if d["estado"] == "vigente" else "vigente"
            if c3.button(f"Marcar {nuevo}", key=f"vig-{d['id']}"):
                accion(api, "PATCH", f"/documentos/{d['id']}", json={"estado": nuevo})
                st.rerun()
    if usuario["rol"] != "admin_corpus":
        return
    st.subheader("Cargar documento")
    with st.form("carga", clear_on_submit=True):
        archivo = st.file_uploader("Archivo PDF o DOCX", type=["pdf", "docx"])
        c1, c2 = st.columns(2)
        titulo = c1.text_input("Título")
        tipo = c2.selectbox("Tipo", ["normativa", "perfil_egreso", "malla", "contenidos_minimos",
                                     "silabo_aprobado", "plantilla"])
        c3, c4, c5 = st.columns(3)
        carrera = c3.text_input("Carrera (TODAS si es institucional)", "ITI")
        version = c4.text_input("Versión")
        fecha = c5.date_input("Fecha de vigencia")
        if st.form_submit_button("Cargar e indexar", type="primary") and archivo:
            r = accion(api, "POST", "/documentos", files={"archivo": (archivo.name, archivo.getvalue())},
                       data={"titulo": titulo, "tipo": tipo, "carrera": carrera, "version": version,
                             "fecha_vigencia": fecha.isoformat()}, exito="Documento indexado")
            if r:
                st.rerun()


def pantalla_buscar() -> None:
    st.header("Consulta directa al recuperador")
    consulta = st.text_input("Consulta")
    carrera = st.text_input("Carrera", "ITI")
    if consulta:
        for r in api("POST", "/buscar", json={"consulta": consulta, "carrera": carrera or None}):
            with st.expander(f"{r['cita']} · léxico {r['puntaje_lexico']:.2f}"):
                st.caption(" > ".join(r["fragmento"]["ruta_seccion"]))
                st.write(r["fragmento"]["texto"])


# --- navegación ---------------------------------------------------------------------------

def main() -> None:
    if "usuario" not in st.session_state:
        pantalla_login()
        return
    usuario = st.session_state["usuario"]
    vistas = ["Mis sílabos", "Nuevo sílabo", "Revisión", "Corpus", "Buscar"]
    if usuario["rol"] == "admin_corpus":
        vistas = ["Corpus", "Buscar"]
    with st.sidebar:
        st.markdown(f"**{usuario['nombre']}** · {usuario['rol']}")
        vista = st.radio("Ir a", vistas, index=vistas.index(st.session_state.get("vista", vistas[0]))
                         if st.session_state.get("vista") in vistas else 0)
        st.session_state["vista"] = vista
        if st.button("Cerrar sesión"):
            st.session_state.clear()
            st.rerun()
    {"Mis sílabos": lambda: pantalla_silabos(usuario), "Nuevo sílabo": pantalla_nuevo,
     "Revisión": pantalla_revision, "Corpus": lambda: pantalla_corpus(usuario),
     "Buscar": pantalla_buscar}[vista]()


main()
