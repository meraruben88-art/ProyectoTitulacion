"""Evaluación del prototipo (SPEC, sección 11) con un solo comando: `syllabusai evaluar`.

Monta un entorno aislado desde cero (base relacional y vectorial en memoria, corpus de
EJEMPLO), con lo que además comprueba que la ingesta se reproduce en un entorno limpio
(criterio de aceptación 5). Luego mide:

- Recuperación: Recall@k y MRR sobre `eval/consultas_recuperacion.yaml`, y que ninguna consulta
  devuelva fragmentos de documentos obsoletos.
- Agente: los casos piloto de `eval/casos_piloto.yaml` (cumplimiento de lo que pidió el docente,
  completitud al primer intento, corrección de citas, coherencia curricular, esfuerzo de
  corrección, latencia) y los casos adversos (abstención, rechazo, descarte).
- Usuarios: tiempo manual frente a asistido, SUS, rúbrica de calidad y fidelidad, a partir de
  `eval/datos_simulados/` (FICTICIOS hasta el piloto real).

Escribe `informe_evaluacion.md`, `resultados.json` y los sílabos exportados en `eval/resultados/`.
"""

import csv
import json
import shutil
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from syllabusai.config import RAIZ, Config, ConfigBaseVectorial, cargar_config
from syllabusai.db.modelos import (
    Asignatura,
    Documento,
    EstadoDocumento,
    Evento,
    OrigenVersion,
    Rol,
    Seccion,
    TipoDocumento,
    Usuario,
    VersionSeccion,
)
from syllabusai.retrieval.lexico import normalizar

EVAL = RAIZ / "eval"
SALIDA = EVAL / "resultados"

# Metas propuestas del SPEC (sección 11); las de usuarios se aplican a los datos simulados.
METAS = {
    "recall": 0.85, "abstencion": 0.90, "citas": 0.95, "completitud": 0.95, "coherencia": 1.0,
    "calidad": 4.0, "reduccion_tiempo": 0.50, "sus": 70, "fidelidad": 0.90, "seccion_s": 60,
}


def _n(texto: Any) -> str:
    return " ".join(normalizar(str(texto)).split())


# --- utilidades puras (probadas en tests/test_evaluacion.py) -----------------------------------

def es_relevante(fragmento, criterios: list[dict]) -> bool:
    titulo, ruta, texto = _n(fragmento.titulo), _n(" > ".join(fragmento.ruta_seccion)), _n(fragmento.texto)
    for c in criterios:
        if _n(c["documento"]) not in titulo:
            continue
        if ("seccion" in c and _n(c["seccion"]) in ruta) or ("texto" in c and _n(c["texto"]) in texto):
            return True
    return False


def recall_y_rr(relevancias: list[bool], total_relevantes: int) -> tuple[float, float]:
    """Recall@k (sobre los relevantes que existen en el índice) y rango recíproco del primero."""
    encontrados = sum(relevancias)
    recall = encontrados / total_relevantes if total_relevantes else 0.0
    rr = next((1 / (i + 1) for i, r in enumerate(relevancias) if r), 0.0)
    return min(recall, 1.0), rr


def puntaje_sus(respuestas: list[int]) -> float:
    """SUS estándar: ítems impares (x-1), pares (5-x), suma × 2,5."""
    return sum((x - 1) if i % 2 == 0 else (5 - x) for i, x in enumerate(respuestas)) * 2.5


def valores(contenido: Any, ruta: str) -> list[Any]:
    """Valores de `ruta` («momentos[*].evaluacion.peso», «resultados[1].enunciado»)."""
    actuales = [contenido]
    for parte in ruta.split("."):
        nombre, _, indice = parte.partition("[")
        siguientes = []
        for actual in actuales:
            valor = actual.get(nombre) if isinstance(actual, dict) else None
            if indice:
                i = indice.rstrip("]")
                if not isinstance(valor, list):
                    continue
                siguientes += valor if i == "*" else valor[int(i):int(i) + 1]
            else:
                siguientes.append(valor)
        actuales = siguientes
    return actuales


def verificar(contenido: dict, regla: dict) -> tuple[bool, Any]:
    encontrados = valores(contenido, regla["ruta"])
    if "igual" in regla:
        esperado = regla["igual"]
        obtenido = encontrados if isinstance(esperado, list) and "[*]" in regla["ruta"] else (
            encontrados[0] if encontrados else None)
        return obtenido == esperado, obtenido
    textos = [_n(json.dumps(v, ensure_ascii=False)) if not isinstance(v, str) else _n(v) for v in encontrados]
    if "contiene" in regla:
        return bool(textos) and all(_n(regla["contiene"]) in t for t in textos), encontrados
    if "no_contiene" in regla:
        return all(_n(regla["no_contiene"]) not in t for t in textos), encontrados
    if "incluye" in regla:
        objetivo = _n(regla["incluye"])
        for v in encontrados:
            lista = v if isinstance(v, list) else [v]
            if any(_n(x) == objetivo for x in lista):
                return True, encontrados
        return False, encontrados
    raise ValueError(f"Regla de verificación sin operador: {regla}")


# --- entorno aislado ---------------------------------------------------------------------------

def _entorno(tmp: Path, base: Config) -> Config:
    config = base.model_copy(deep=True)
    config.base_datos.url = "sqlite://"
    config.corpus.directorio = tmp / "corpus"
    config.base_vectorial = ConfigBaseVectorial(ruta=None, url=None)
    config.exportacion.directorio = tmp / "exportados"
    config.telemetria.directorio = tmp / "metricas"
    config.llm.retardo_simulado_ms = 0
    return config


def _preparar(c, manifiesto_ruta: Path, catalogo_adverso: dict) -> dict:
    from syllabusai.ejemplo import CATALOGO, generar_documentos
    from syllabusai.ingest.catalogo import Catalogo, importar_catalogo
    from syllabusai.ingest.pipeline import cargar_manifiesto, ingestar_manifiesto
    from syllabusai.seguridad import crear_usuario

    generar_documentos()
    inicio = time.perf_counter()
    with c.fabrica() as s:
        admin = crear_usuario(s, "Admin evaluación", "admin@eval", "x", Rol.ADMIN_CORPUS)
        crear_usuario(s, "Docente evaluación", "docente@eval", "x", Rol.DOCENTE)
        importar_catalogo(s, CATALOGO)
        ruta = Path(c.config.corpus.directorio).parent / "catalogo_adverso.yaml"
        ruta.write_text(yaml.safe_dump(Catalogo.model_validate(catalogo_adverso).model_dump(mode="json"),
                                       allow_unicode=True), encoding="utf-8")
        importar_catalogo(s, ruta)
        s.commit()
        resultados = ingestar_manifiesto(s, c.recuperador, cargar_manifiesto(manifiesto_ruta),
                                         admin.id, c.config)
        return {
            "documentos": len(resultados),
            "fragmentos": sum(n for _, n in resultados),
            "obsoletos": sum(1 for d, _ in resultados if d.estado == EstadoDocumento.OBSOLETO),
            "segundos": round(time.perf_counter() - inicio, 1),
        }


# --- recuperación ------------------------------------------------------------------------------

def evaluar_recuperacion(c, ruta: Path) -> dict:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    k = datos.get("k", 5)
    todos = c.recuperador.almacen.todos()
    filas = []
    for q in datos["consultas"]:
        filtros = q.get("filtros") or {}
        tipos = [TipoDocumento(t) for t in filtros["tipos"]] if filtros.get("tipos") else None
        resultados = c.recuperador.buscar(q["consulta"], tipos=tipos, carrera=filtros.get("carrera"), k=k)
        relevancias = [es_relevante(r.fragmento, q["relevantes"]) for r in resultados]
        # Relevantes que existen en el índice (vigentes y del tipo pedido): denominador del recall.
        total = sum(1 for f in todos if f.vigente and (tipos is None or f.tipo_documento in tipos)
                    and es_relevante(f, q["relevantes"]))
        recall, rr = recall_y_rr(relevancias, min(total, k))
        filas.append({"id": q["id"], "consulta": q["consulta"], "recall": round(recall, 3),
                      "rr": round(rr, 3), "relevantes_en_indice": total,
                      "top": [r.fragmento.fragmento_id for r in resultados]})
    obsoletas = []
    for q in datos.get("obsoletas", []):
        resultados = c.recuperador.buscar(q["consulta"], k=k)
        obsoletas.append({"id": q["id"], "consulta": q["consulta"],
                          "obsoletos_devueltos": sum(1 for r in resultados if not r.fragmento.vigente)})
    return {
        "k": k,
        "recall": round(statistics.mean(f["recall"] for f in filas), 3),
        "mrr": round(statistics.mean(f["rr"] for f in filas), 3),
        "consultas": filas,
        "sin_obsoletos": round(sum(1 for o in obsoletas if o["obsoletos_devueltos"] == 0)
                               / max(len(obsoletas), 1), 3),
        "obsoletas": obsoletas,
    }


# --- agente ------------------------------------------------------------------------------------

def _ids(c, codigo: str) -> tuple[int, int]:
    with c.fabrica() as s:
        asignatura = s.scalar(select(Asignatura).where(Asignatura.codigo == codigo))
        docente = s.scalar(select(Usuario).where(Usuario.correo == "docente@eval"))
        return asignatura.id, docente.id


def _seccion(c, silabo_id: int, clave: str) -> dict:
    return next(x for x in c.servicio.estado(silabo_id)["secciones"] if x["clave"] == clave)


def _caso_piloto(c, caso: dict, exportados: Path) -> dict:
    asignatura_id, docente_id = _ids(c, caso["asignatura"])
    datos = dict(caso["datos_generales"])
    datos["preferencias"] = caso.get("preferencias") or {}
    datos["indicaciones_generales"] = caso.get("indicaciones_generales")
    silabo_id = c.servicio.crear_silabo(docente_id, asignatura_id, "B26", datos)
    pasos = {}
    for paso in caso.get("conversacion", []):
        pasos.setdefault(paso["seccion"], []).append(paso)
    notas, error = [], None
    pausa = c.orquestador.iniciar(silabo_id)
    while pausa["tipo"] == "revision_seccion":
        clave = pausa["clave"]
        for paso in pasos.pop(clave, []):
            if "editar" in paso:  # el docente corrige a mano: mide la distancia de edición
                contenido = _seccion(c, silabo_id, clave)["contenido"] | paso["editar"]
                pausa = c.orquestador.reanudar(silabo_id, {"accion": "editar", "contenido": contenido})
                notas.append({"seccion": clave, "indicacion": f"(edita a mano: {', '.join(paso['editar'])})",
                              "respuesta": "Edición guardada y validada."})
                continue
            pausa = c.orquestador.reanudar(silabo_id, {"accion": "regenerar",
                                                       "indicacion": paso["indicacion"]})
            notas.append({"seccion": clave, "indicacion": paso["indicacion"],
                          "respuesta": _seccion(c, silabo_id, clave)["nota"]})
        if _seccion(c, silabo_id, clave)["estado"] == "abstenida":
            error = f"La sección {clave} se abstuvo"
            break
        pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
    if pausa["tipo"] == "correccion":
        error = "; ".join(f"{h['regla']}: {h['mensaje']}" for h in pausa["hallazgos"])
    secciones = {x["clave"]: x["contenido"] for x in c.servicio.estado(silabo_id)["secciones"]}
    verificaciones = []
    for regla in caso.get("verificar", []):
        ok, obtenido = verificar(secciones.get(regla["seccion"]) or {}, regla)
        verificaciones.append({"regla": regla, "cumple": ok, "obtenido": None if ok else obtenido})
    archivos = []
    if error is None and pausa["tipo"] == "terminado":
        for formato in ("docx", "pdf"):
            ruta = c.servicio.exportar(silabo_id, formato)
            destino = exportados / f"{caso['id']}_{ruta.name}"
            shutil.copy(ruta, destino)
            archivos.append(destino.name)
        traza = ruta.parent / f"{ruta.stem}_trazabilidad.docx"
        if traza.exists():
            shutil.copy(traza, exportados / f"{caso['id']}_{traza.name}")
    return {"id": caso["id"], "asignatura": caso["asignatura"], "silabo_id": silabo_id,
            "error": error, "verificaciones": verificaciones, "conversacion": notas,
            "exportados": archivos}


def _caso_adverso(c, caso: dict) -> dict:
    from syllabusai.ingest.pipeline import sincronizar_vigencia
    from syllabusai.ingest.registro import cambiar_estado
    from syllabusai.llm.base import RespuestaLLM

    asignatura_id, docente_id = _ids(c, caso["asignatura"])
    clave = caso["esperado"]["seccion"]
    datos = {"semanas_periodo": 16, "contexto_problema": "Necesidad documentada de ejemplo",
             "fuentes_problema": "Fuente ficticia", "escenario": "la carrera"}
    restaurar, llm_original = None, c.servicio.llm
    if caso["tipo"] == "sin_contexto":
        datos["contexto_problema"] = ""
    elif caso["tipo"] == "perfil_obsoleto":
        with c.fabrica() as s:
            perfil = s.scalar(select(Documento).where(Documento.tipo == TipoDocumento.PERFIL_EGRESO,
                                                      Documento.estado == EstadoDocumento.VIGENTE))
            cambiar_estado(s, perfil.id, EstadoDocumento.OBSOLETO)
            sincronizar_vigencia(s, c.recuperador)
            s.commit()
            restaurar = perfil.id
    elif caso["tipo"] == "modelo_que_inventa":
        class ModeloQueInventa(type(llm_original)):
            def generar(self, solicitud):
                respuesta = super().generar(solicitud)
                datos_ = dict(respuesta.datos)
                datos_["fuentes"] = list(datos_["fuentes"]) + ["d999-f9999"]
                if solicitud.clave == "recursos":
                    contenido = dict(datos_["contenido"])
                    contenido["bibliografia_basica"] = list(contenido.get("bibliografia_basica", [])) + [
                        "Pérez, J. (2023). Manual inventado de bases de datos. Editorial Ficticia."]
                    datos_["contenido"] = contenido
                return RespuestaLLM(datos_, respuesta.texto, respuesta.latencia_ms, respuesta.ttft_ms,
                                    respuesta.tokens_in, respuesta.tokens_out, respuesta.modelo)
        c.servicio.llm = ModeloQueInventa()
    try:
        silabo_id = c.servicio.crear_silabo(docente_id, asignatura_id, "B26", datos)
        pausa = c.orquestador.iniciar(silabo_id)
        while pausa["tipo"] == "revision_seccion" and pausa["clave"] != clave:
            if _seccion(c, silabo_id, pausa["clave"])["estado"] == "abstenida":
                break
            pausa = c.orquestador.reanudar(silabo_id, {"accion": "aprobar"})
        if caso.get("indicacion") and pausa.get("clave") == clave:
            c.orquestador.reanudar(silabo_id, {"accion": "regenerar", "indicacion": caso["indicacion"]})
        seccion = _seccion(c, silabo_id, pausa.get("clave") or clave)
        hallazgos = [h for h in c.servicio.estado(silabo_id)["hallazgos"]
                     if h["seccion"] == seccion["clave"]]
    finally:
        c.servicio.llm = llm_original
        if restaurar is not None:
            with c.fabrica() as s:
                cambiar_estado(s, restaurar, EstadoDocumento.VIGENTE)
                sincronizar_vigencia(s, c.recuperador)
                s.commit()

    abstuvo = seccion["estado"] == "abstenida"
    contenido, nota = seccion["contenido"] or {}, seccion["nota"] or ""
    if caso["tipo"] == "modelo_que_inventa":
        correcto = (seccion["clave"] == clave and all(x["fragmento_id"] != "d999-f9999" for x in seccion["citas"])
                    and not any("inventado" in r for r in contenido.get("bibliografia_basica", []))
                    and any(h["regla"] == "RF-13" for h in hallazgos))
    elif caso["tipo"] == "pesos_imposibles":
        pesos = [m["evaluacion"]["peso"] for m in contenido.get("momentos", [])]
        correcto = pesos == [20, 30, 30, 20] and "no permiten sumar 100" in nota
    elif caso["tipo"] == "cambio_oficial":
        correcto = len(contenido.get("resultados", [])) == 3 and "Comité Curricular" in nota
    else:
        correcto = seccion["clave"] == clave and abstuvo == caso["esperado"]["abstencion"]
    return {"id": caso["id"], "tipo": caso["tipo"], "descripcion": caso["descripcion"],
            "seccion": seccion["clave"], "abstencion": abstuvo, "correcto": correcto,
            "respuesta_agente": nota}


def _metricas_de_corpus_y_eventos(c, silabos: list[int]) -> dict:
    from syllabusai.ingest.catalogo import ficha_de
    from syllabusai.validation import reglas

    citas_total = citas_ok = 0
    secciones_generadas = completas = 0
    latencias, ttfts = [], []
    distancias = []
    with c.fabrica() as s:
        vigentes = {d.id for d in s.scalars(select(Documento).where(Documento.estado == EstadoDocumento.VIGENTE))}
        for silabo_id in silabos:
            secciones = s.scalars(select(Seccion).where(Seccion.silabo_id == silabo_id)).all()
            for seccion in secciones:
                versiones = s.scalars(select(VersionSeccion).where(VersionSeccion.seccion_id == seccion.id)
                                      .order_by(VersionSeccion.n)).all()
                primera = next((v for v in versiones if v.origen == OrigenVersion.AGENTE), None)
                if primera is not None and seccion.clave != "identificacion":
                    secciones_generadas += 1
                    ficha = ficha_de(seccion.silabo.asignatura)
                    rf31 = [h for h in reglas.validar_seccion(seccion.clave, primera.contenido, ficha,
                                                               seccion.silabo.datos_generales)
                            if h.regla == "RF-31"]
                    completas += not rf31
                for v in versiones:
                    fragmentos = c.recuperador.almacen.obtener([x.fragmento_id for x in v.citas])
                    for cita in v.citas:
                        citas_total += 1
                        f = fragmentos.get(cita.fragmento_id)
                        citas_ok += bool(f and f.documento_id == cita.documento_id
                                         and f.pagina_inicio == cita.pagina
                                         and cita.documento_id in vigentes)
            for e in s.scalars(select(Evento).where(Evento.silabo_id == silabo_id)):
                if e.tipo == "generacion" and e.payload.get("modelo") not in (None, "importacion"):
                    latencias.append(e.payload.get("latencia_total_ms") or e.latencia_ms or 0)
                    if e.ttft_ms is not None:
                        ttfts.append(e.ttft_ms)
                if e.tipo == "correccion":
                    distancias.append(e.payload.get("distancia_edicion", 0))
    return {
        "citas": {"total": citas_total, "correctas": citas_ok,
                  "porcentaje": round(citas_ok / citas_total, 3) if citas_total else None},
        "completitud": {"secciones": secciones_generadas, "completas_primer_intento": completas,
                        "porcentaje": round(completas / secciones_generadas, 3) if secciones_generadas else None},
        "latencia_seccion_ms": {"media": round(statistics.mean(latencias), 1) if latencias else None,
                                "maxima": round(max(latencias), 1) if latencias else None},
        "ttft_ms": round(statistics.mean(ttfts), 1) if ttfts else None,
        "distancia_edicion": distancias,
    }


def _coherencia(c, silabos: list[int]) -> dict:
    """RA cubiertos a la vez por evidencia (7.4), momento (7.6) y evaluación (7.7) al exportar."""
    total = cubiertos = 0
    for silabo_id in silabos:
        secciones = {x["clave"]: x["contenido"] or {} for x in c.servicio.estado(silabo_id)["secciones"]}
        en_momentos = {ra for m in secciones.get("planeacion_momentos", {}).get("momentos", []) for ra in m["ra"]}
        evaluados = {ra for e in secciones.get("evaluacion", {}).get("evidencias", []) for ra in e["ra"]}
        for ra in secciones.get("resultados_aprendizaje", {}).get("resultados", []):
            total += 1
            cubiertos += bool(ra.get("evidencia")) and ra["codigo"] in en_momentos and ra["codigo"] in evaluados
    return {"ra": total, "cubiertos": cubiertos, "porcentaje": round(cubiertos / total, 3) if total else None}


# --- usuarios (datos simulados) ------------------------------------------------------------

def _csv(ruta: Path) -> list[dict]:
    with ruta.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def evaluar_usuarios(carpeta: Path) -> dict:
    tiempos = _csv(carpeta / "tiempos_EJEMPLO.csv")
    manual = {t["docente"]: int(t["minutos"]) for t in tiempos if t["metodo"] == "manual"}
    asistido = {t["docente"]: int(t["minutos"]) for t in tiempos if t["metodo"] == "asistido"}
    reducciones = [1 - asistido[d] / manual[d] for d in manual if d in asistido]
    sus = [puntaje_sus([int(f[f"p{i}"]) for i in range(1, 11)]) for f in _csv(carpeta / "sus_EJEMPLO.csv")]
    rubrica = _csv(carpeta / "rubrica_calidad_EJEMPLO.csv")
    criterios = [k for k in rubrica[0] if k not in ("evaluador", "asignatura", "metodo")]

    def media(metodo):
        return round(statistics.mean(int(f[k]) for f in rubrica if f["metodo"] == metodo for k in criterios), 2)

    fidelidad = _csv(carpeta / "fidelidad_EJEMPLO.csv")
    sustentadas = sum(1 if f["sustentada"] == "si" else 0.5 if f["sustentada"] == "parcial" else 0
                      for f in fidelidad)
    return {
        "ficticios": True,
        "tiempo": {"manual_min": round(statistics.mean(manual.values()), 1),
                   "asistido_min": round(statistics.mean(asistido.values()), 1),
                   "reduccion": round(statistics.mean(reducciones), 3)},
        "sus": {"media": round(statistics.mean(sus), 1), "por_docente": sus},
        "calidad": {"manual": media("manual"), "asistido": media("asistido"), "criterios": criterios},
        "fidelidad": {"afirmaciones": len(fidelidad), "porcentaje": round(sustentadas / len(fidelidad), 3)},
    }


# --- orquestación e informe --------------------------------------------------------------------

def evaluar(salida: Path = SALIDA, config: Config | None = None) -> dict:
    from syllabusai.contenedor import crear_contenedor
    from syllabusai.ejemplo import MANIFIESTO

    casos = yaml.safe_load((EVAL / "casos_piloto.yaml").read_text(encoding="utf-8"))
    salida.mkdir(parents=True, exist_ok=True)
    exportados = salida / "silabos"
    shutil.rmtree(exportados, ignore_errors=True)
    exportados.mkdir()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        c = crear_contenedor(_entorno(Path(tmp), config or cargar_config()), checkpoints_en_memoria=True)
        try:
            print("Ingestando el corpus de ejemplo desde cero…")
            resultados: dict[str, Any] = {"fecha": datetime.now(UTC).isoformat(timespec="seconds"),
                                          "modelo": c.llm.nombre}
            resultados["reproducibilidad"] = _preparar(c, MANIFIESTO, casos["catalogo_adverso"])
            print("Evaluando la recuperación…")
            resultados["recuperacion"] = evaluar_recuperacion(c, EVAL / "consultas_recuperacion.yaml")
            print("Ejecutando los casos piloto…")
            piloto = [_caso_piloto(c, caso, exportados) for caso in casos["piloto"]]
            print("Ejecutando los casos adversos…")
            adversos = [_caso_adverso(c, caso) for caso in casos["adversos"]]
            silabos = [p["silabo_id"] for p in piloto]
            verificaciones = [v for p in piloto for v in p["verificaciones"]]
            con_abstencion = [a for a in adversos if a["tipo"] in ("sin_contexto", "perfil_obsoleto",
                                                                   "carrera_sin_documentos")]
            resultados["agente"] = {
                "piloto": piloto,
                "adversos": adversos,
                "cumplimiento_indicaciones": round(sum(v["cumple"] for v in verificaciones)
                                                   / len(verificaciones), 3),
                "abstencion": round(sum(a["abstencion"] for a in con_abstencion) / len(con_abstencion), 3),
                "adversos_correctos": round(sum(a["correcto"] for a in adversos) / len(adversos), 3),
                "exportados": sum(1 for p in piloto if p["exportados"]),
                "coherencia": _coherencia(c, [p["silabo_id"] for p in piloto if p["exportados"]]),
                **_metricas_de_corpus_y_eventos(c, silabos),
            }
        finally:
            c.cerrar()
    resultados["usuarios"] = evaluar_usuarios(EVAL / "datos_simulados")
    (salida / "resultados.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    (salida / "informe_evaluacion.md").write_text(informe(resultados), encoding="utf-8")
    return resultados


def _dec(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f} %".replace(".", ",")


def _cumple(valor, meta, mayor=True) -> str:
    if valor is None:
        return "—"
    return "✅" if (valor >= meta if mayor else valor <= meta) else "❌"


def informe(r: dict) -> str:
    rec, ag, us, rep = r["recuperacion"], r["agente"], r["usuarios"], r["reproducibilidad"]
    lat_s = (ag["latencia_seccion_ms"]["media"] or 0) / 1000
    filas = [
        ("Recuperación", f"Recall@{rec['k']}", _pct(rec["recall"]), "≥ 85 %", _cumple(rec["recall"], METAS["recall"])),
        ("Recuperación", "MRR", f"{rec['mrr']:.3f}".replace(".", ","), "informativo", "—"),
        ("Recuperación", "Consultas sin fragmentos obsoletos", _pct(rec["sin_obsoletos"]), "100 %",
         _cumple(rec["sin_obsoletos"], 1.0)),
        ("Fidelidad a las fuentes ⚠️", "Afirmaciones sustentadas (revisión manual)",
         _pct(us["fidelidad"]["porcentaje"]), "≥ 90 %", _cumple(us["fidelidad"]["porcentaje"], METAS["fidelidad"])),
        ("Corrección de citas", "Citas a documento vigente, fragmento y página correctos",
         _pct(ag["citas"]["porcentaje"]), "≥ 95 %", _cumple(ag["citas"]["porcentaje"], METAS["citas"])),
        ("Abstención", "Casos sin evidencia en que el agente se abstiene", _pct(ag["abstencion"]),
         "≥ 90 %", _cumple(ag["abstencion"], METAS["abstencion"])),
        ("Completitud", "Secciones sin campos vacíos al primer intento", _pct(ag["completitud"]["porcentaje"]),
         "≥ 95 %", _cumple(ag["completitud"]["porcentaje"], METAS["completitud"])),
        ("Coherencia curricular", "RA con evidencia, momento y evaluación al exportar",
         _pct(ag["coherencia"]["porcentaje"]), "100 %", _cumple(ag["coherencia"]["porcentaje"], METAS["coherencia"])),
        ("Atención al docente", "Pedidos del docente cumplidos en el sílabo final",
         _pct(ag["cumplimiento_indicaciones"]), "informativo", "—"),
        ("Atención al docente", "Casos adversos resueltos correctamente", _pct(ag["adversos_correctos"]),
         "100 %", _cumple(ag["adversos_correctos"], 1.0)),
        ("Calidad documental ⚠️", "Rúbrica académica (1–5), asistido / manual",
         f"{us['calidad']['asistido']} / {us['calidad']['manual']}".replace(".", ","), "≥ 4",
         _cumple(us["calidad"]["asistido"], METAS["calidad"])),
        ("Reducción de tiempo ⚠️", "Tiempo asistido frente a manual",
         f"−{_pct(us['tiempo']['reduccion'])} ({us['tiempo']['asistido_min']} vs {us['tiempo']['manual_min']} min)",
         "≥ 50 % menos", _cumple(us["tiempo"]["reduccion"], METAS["reduccion_tiempo"])),
        ("Esfuerzo de corrección", "Distancia de edición (palabras)",
         (f"{statistics.mean(ag['distancia_edicion']):.0f} palabras en {len(ag['distancia_edicion'])} "
          "edición(es)" if ag["distancia_edicion"] else "sin ediciones en los casos"), "informativo", "—"),
        ("Usabilidad ⚠️", "SUS", f"{us['sus']['media']}".replace(".", ","), "≥ 70",
         _cumple(us["sus"]["media"], METAS["sus"])),
        ("Rendimiento técnico", "Latencia media por sección", f"{lat_s:.3f} s".replace(".", ","), "≤ 60 s",
         _cumple(lat_s, METAS["seccion_s"], mayor=False)),
    ]
    lineas = [
        "# Informe de evaluación de SyllabusAI",
        "",
        f"Generado el {r['fecha']} con `syllabusai evaluar` · modelo: **{r['modelo']}**.",
        "",
        ("> **Advertencia.** Las métricas automáticas se calcularon sobre el corpus y el catálogo "
         "de EJEMPLO, con el modelo simulado: prueban que el pipeline de evaluación funciona, no la "
         "calidad de redacción de Qwen3-8B. Las filas marcadas con ⚠️ salen de "
         "`eval/datos_simulados/`, que son datos **FICTICIOS** hasta el piloto con docentes."),
        "",
        "## Resumen frente a las metas del SPEC (sección 11)",
        "",
        "| Dimensión | Indicador | Resultado | Meta | Cumple |",
        "|---|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in filas],
        "",
        "## Reproducibilidad de la ingesta",
        "",
        f"El corpus se ingestó desde cero en un entorno limpio: {rep['documentos']} documentos, "
        f"{rep['fragmentos']} fragmentos, {rep['obsoletos']} documento(s) obsoleto(s), "
        f"{rep['segundos']} s.".replace(".", ",", 1),
        "",
        "## Recuperación por consulta",
        "",
        (f"Recall@{rec['k']} normalizado: relevantes recuperados entre los {rec['k']} primeros, "
         f"dividido por el mínimo entre {rec['k']} y los relevantes vigentes del índice. RR: inverso "
         "de la posición del primer relevante."),
        "",
        "| ID | Consulta | Recall | RR |",
        "|---|---|---|---|",
        *[f"| {q['id']} | {q['consulta']} | {_dec(q['recall'])} | {_dec(q['rr'])} |" for q in rec["consultas"]],
        "",
        "## Casos piloto: ¿el agente hizo lo que pidió el docente?",
        "",
    ]
    for p in ag["piloto"]:
        cumplidas = sum(v["cumple"] for v in p["verificaciones"])
        lineas += [f"### {p['id']} · {p['asignatura']} — {cumplidas}/{len(p['verificaciones'])} "
                   "verificaciones" + (f" · ⛔ {p['error']}" if p["error"] else ""), ""]
        for n in p["conversacion"]:
            lineas += [f"- **Docente ({n['seccion']}):** {n['indicacion']}",
                       f"  - **Agente:** {n['respuesta']}"]
        fallidas = [v for v in p["verificaciones"] if not v["cumple"]]
        for v in fallidas:
            lineas.append(f"- ❌ `{v['regla']['seccion']}.{v['regla']['ruta']}`: se obtuvo {v['obtenido']}")
        lineas += [f"- Exportados: {', '.join(p['exportados']) or 'ninguno'}", ""]
    lineas += ["## Casos adversos", "", "| ID | Caso | Correcto | Respuesta del agente |", "|---|---|---|---|"]
    for a in ag["adversos"]:
        respuesta = (a["respuesta_agente"] or "").replace("|", "/")[:220]
        lineas.append(f"| {a['id']} | {a['descripcion']} | {'✅' if a['correcto'] else '❌'} | {respuesta} |")
    lineas += ["", "## Datos de usuarios (FICTICIOS)", "",
               (f"- Tiempo medio manual: {us['tiempo']['manual_min']} min; asistido: "
                f"{us['tiempo']['asistido_min']} min."),
               f"- SUS por docente: {'; '.join(_dec(x) for x in us['sus']['por_docente'])}.",
               (f"- Rúbrica de calidad ({', '.join(us['calidad']['criterios'])}): asistido "
                f"{_dec(us['calidad']['asistido'])}, manual {_dec(us['calidad']['manual'])}."),
               f"- Fidelidad: {us['fidelidad']['afirmaciones']} afirmaciones revisadas.", ""]
    return "\n".join(lineas)
