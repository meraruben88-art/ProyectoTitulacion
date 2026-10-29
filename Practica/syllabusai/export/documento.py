"""Documento lógico del sílabo, independiente del formato de archivo (RF-40, RF-41).

Se construye una sola vez a partir del contenido aprobado y lo dibujan dos renderizadores, DOCX
y PDF, de modo que ambos archivos son equivalentes. Sigue el orden y las tablas del formato de
la Propuesta 2026 (secciones 7.1 a 7.9).
"""

from dataclasses import dataclass, field

from syllabusai.formato.catalogos import NIVELES_RUBRICA


@dataclass
class Titulo:
    texto: str
    nivel: int = 1


@dataclass
class Parrafo:
    texto: str
    cursiva: bool = False


@dataclass
class Tabla:
    filas: list[list[str]]
    encabezado: bool = True  # la primera fila es encabezado
    clave_valor: bool = False  # tabla de dos columnas «campo | valor»
    anchos: list[float] = field(default_factory=list)  # proporciones por columna


Elemento = Titulo | Parrafo | Tabla


def _lista(valores) -> str:
    valores = [v for v in (valores or []) if str(v).strip()]
    return "\n".join(f"• {v}" for v in valores) if valores else "—"


def _txt(valor) -> str:
    if valor is None or valor == "" or valor == []:
        return "—"
    return str(valor)


def construir(datos: dict) -> list[Elemento]:
    s = datos["secciones"]
    t = datos["titulos"]
    ident = s.get("identificacion", {})
    el: list[Elemento] = [
        Titulo("UNIVERSIDAD TECNOLÓGICA INDOAMÉRICA", 0),
        Titulo(f"{datos['formato']['nombre'].upper()} ({datos['formato']['version']})", 0),
        Parrafo(ident.get("nombre_pf", "")),
    ]

    el += [Titulo(t["identificacion"]), Tabla(clave_valor=True, encabezado=False, filas=[
        ["Nombre del Proyecto Formativo", _txt(ident.get("nombre_pf"))],
        ["Código", _txt(ident.get("codigo"))],
        ["Versión", _txt(ident.get("version"))],
        ["Facultad", _txt(ident.get("facultad"))],
        ["Carrera / Programa", _txt(ident.get("carrera"))],
        ["Nivel / Periodo de la malla", _txt(ident.get("nivel"))],
        ["Modalidad", _txt(ident.get("modalidad"))],
        ["Unidad de Organización Curricular", _txt(ident.get("unidad_organizacion"))],
        ["Periodo académico", _txt(ident.get("periodo_academico"))],
        ["Créditos", _txt(ident.get("creditos"))],
        ["Horas de contacto docente", _txt(ident.get("horas_contacto"))],
        ["Horas práctico-experimentales", _txt(ident.get("horas_practicas"))],
        ["Horas de aprendizaje autónomo", _txt(ident.get("horas_autonomas"))],
        ["Total de horas", _txt(ident.get("total_horas"))],
        ["Prerrequisitos", _lista(ident.get("prerrequisitos"))],
        ["Correquisitos / PF articulados", _lista(ident.get("correquisitos"))],
        ["Docente responsable", _txt(ident.get("docente"))],
        ["Correo institucional", _txt(ident.get("correo_docente"))],
    ])]

    a = s.get("anclaje_curricular", {})
    ejes = [f"{e.get('eje')}: {e.get('justificacion')}" for e in a.get("ejes", [])]
    meta = a.get("metacompetencia", "")
    if a.get("metacompetencia_secundaria"):
        meta += f"\nSecundaria: {a['metacompetencia_secundaria']}"
    el += [Titulo(t["anclaje_curricular"]), Tabla(clave_valor=True, encabezado=False, filas=[
        ["Competencia específica del perfil de egreso", _txt(a.get("competencia_especifica"))],
        ["Desempeño profesional central del PF", _txt(a.get("desempeno_central"))],
        ["Metacompetencia transversal", _txt(meta)],
        ["Habilidad blanda por metacompetencia", _lista(a.get("habilidades_blandas"))],
        ["Ejes del Modelo Educativo", _lista(ejes)],
        ["Accesibilidad / atención a necesidades educativas específicas", _txt(a.get("accesibilidad_nee"))],
        ["Articulación con otros PF", _txt(a.get("articulacion_pf"))],
        ["PIS del periodo", _txt(a.get("pis_periodo"))],
        ["Aporte del PF al PIS", _txt(a.get("aporte_pis"))],
        ["Microcredencial / credencial", _txt(a.get("microcredencial") or "No aplica")],
    ])]

    p = s.get("problema_reto", {})
    el += [Titulo(t["problema_reto"]), Tabla(clave_valor=True, encabezado=False, filas=[
        ["Problema / necesidad / oportunidad", _txt(p.get("problema"))],
        ["Pregunta o reto", _txt(p.get("pregunta_reto"))],
        ["Producto, servicio o solución integradora", _txt(p.get("producto_integrador"))],
        ["Escenario / actores del contexto", _txt(p.get("escenario_actores"))],
        ["Criterio de impacto / pertinencia", _txt(p.get("criterio_impacto"))],
    ])]

    resultados = {r["codigo"]: r for r in s.get("resultados_aprendizaje", {}).get("resultados", [])}
    filas_ra = [["RA", "Resultado de aprendizaje", "Evidencia", "Momento(s)"]]
    for i in range(1, 5):
        r = resultados.get(f"RA{i}")
        if r:
            momentos = ", ".join(f"M{m}" for m in r.get("momentos", []))
            filas_ra.append([f"RA{i}", r["enunciado"], _txt(r.get("evidencia")), _txt(momentos)])
        else:
            filas_ra.append([f"RA{i}", "No aplica", "—", "—"])
    el += [Titulo(t["resultados_aprendizaje"]), Tabla(filas_ra, anchos=[0.08, 0.42, 0.35, 0.15])]

    c = s.get("contenidos", {})
    el += [Titulo(t["contenidos"]), Tabla(filas=[
        ["Tipo", "Contenido"],
        ["Contenidos mínimos oficiales", _lista(c.get("contenidos_minimos"))],
        ["Conceptuales - saber conocer", _lista(c.get("conceptuales"))],
        ["Procedimentales - saber hacer", _lista(c.get("procedimentales"))],
        ["Actitudinales/éticos - saber ser y convivir", _lista(c.get("actitudinales"))],
    ], anchos=[0.3, 0.7])]

    momentos = s.get("planeacion_momentos", {}).get("momentos", [])
    el.append(Titulo(t["planeacion_momentos"]))
    for m in momentos:
        ev = m.get("evaluacion") or {}
        total = m.get("horas_contacto", 0) + m.get("horas_practicas", 0) + m.get("horas_autonomas", 0)
        el += [Titulo(f"Momento {m['numero']}. {m.get('nombre', '')}", 2),
               Tabla(clave_valor=True, encabezado=False, filas=[
                   ["Semanas", _txt(m.get("semanas"))],
                   ["RA asociados", _txt(", ".join(m.get("ra", [])))],
                   ["Propósito del momento", _txt(m.get("proposito"))],
                   ["Contacto docente", _txt(m.get("contacto_docente"))],
                   ["Aprendizaje autónomo", _txt(m.get("aprendizaje_autonomo"))],
                   ["Práctico-experimental", _txt(m.get("practico_experimental"))],
                   ["Evidencia / producto parcial", _txt(m.get("evidencia_parcial"))],
                   ["Contenidos conceptuales", _lista(m.get("contenidos_conceptuales"))],
                   ["Contenidos procedimentales", _lista(m.get("contenidos_procedimentales"))],
                   ["Contenidos actitudinales/éticos", _lista(m.get("contenidos_actitudinales"))],
                   ["Política de IA", _txt(m.get("politica_ia"))],
                   ["Horas del momento", (f"Contacto: {m.get('horas_contacto', 0)} | Práctico-"
                                          f"experimental: {m.get('horas_practicas', 0)} | Autónomo: "
                                          f"{m.get('horas_autonomas', 0)} | Total: {total}")],
                   ["Evaluación", (f"Evidencia: {_txt(ev.get('evidencia'))} | Peso: "
                                   f"{ev.get('peso', 0)} % | {_tipos(ev.get('tipos', []))} | "
                                   f"Instrumento: {_txt(ev.get('instrumento'))}")],
                   ["Retroalimentación y mejora", _txt(m.get("retroalimentacion"))],
                   ["Recursos y escenarios", _txt(m.get("recursos"))],
               ])]
    if momentos:
        filas_h = [["Momento", "Contacto", "Práctico-experimental", "Autónomo", "Total"]]
        sumas = [0, 0, 0]
        for m in momentos:
            h = [m.get("horas_contacto", 0), m.get("horas_practicas", 0), m.get("horas_autonomas", 0)]
            sumas = [x + y for x, y in zip(sumas, h, strict=True)]
            filas_h.append([f"M{m['numero']}", *map(str, h), str(sum(h))])
        filas_h.append(["TOTAL", *map(str, sumas), str(sum(sumas))])
        el += [Parrafo("Control de horas: la suma por componente coincide con las horas oficiales "
                       "del PF.", cursiva=True), Tabla(filas_h)]

    ev = s.get("evaluacion", {}).get("evidencias", [])
    filas_r = [["Nivel", "Descriptor institucional de referencia", "Puntaje /10", "Equivalencia"]]
    for n in NIVELES_RUBRICA:
        filas_r.append([f"{n.numero}. {n.nombre}", n.descriptor,
                        f"{n.minimo:.1f}–{n.maximo:.1f}".replace(".", ","), n.equivalencia])
    filas_e = [["RA / evidencia", "Criterios de desempeño", "Peso", "Instrumento", "Oportunidad de mejora"]]
    for e in ev:
        filas_e.append([f"{', '.join(e.get('ra', []))} / {e.get('evidencia', '')}",
                        _lista(e.get("criterios")), f"{e.get('peso', 0)} %",
                        _txt(e.get("instrumento")), _txt(e.get("oportunidad_mejora"))])
    filas_e.append(["TOTAL", "", f"{sum(e.get('peso', 0) for e in ev)} %", "", ""])
    el += [Titulo(t["evaluacion"]), Tabla(filas_r, anchos=[0.17, 0.5, 0.13, 0.2]),
           Tabla(filas_e, anchos=[0.25, 0.32, 0.08, 0.15, 0.2])]

    r = s.get("recursos", {})
    el += [Titulo(t["recursos"]), Tabla(clave_valor=True, encabezado=False, filas=[
        ["Bibliografía básica", _lista(r.get("bibliografia_basica"))],
        ["Bibliografía complementaria", _lista(r.get("bibliografia_complementaria"))],
        ["Bases de datos / recursos digitales", _lista(r.get("bases_datos"))],
        ["Tecnología e IA", _txt(r.get("tecnologia_ia"))],
        ["Escenarios / aliados", _txt(r.get("escenarios"))],
        ["Accesibilidad e inclusión", _txt(r.get("accesibilidad"))],
    ])]

    g = s.get("seguimiento_mejora", {})
    el += [Titulo(t["seguimiento_mejora"]), Tabla(clave_valor=True, encabezado=False, filas=[
        ["Registro del logro de RA", _txt(g.get("registro_logro_ra"))],
        ["Acciones de mejora", _txt(g.get("acciones_mejora"))],
        ["Ajustes para el siguiente periodo", _txt(g.get("ajustes_siguiente_periodo"))],
        ["Cambios que se escalan al Comité Curricular", _txt(g.get("cambios_a_escalar"))],
    ])]

    datos_g = datos["silabo"]["datos_generales"]
    el += [Titulo("7.9. Aprobación"), Tabla(filas=[
        ["Elaborado por", "Aprobado por"],
        [(f"Docente responsable\nNombre: {_txt(ident.get('docente'))}\nFecha: "
          f"{datos_g.get('fecha_elaboracion') or '[ ]'}\nFirma:"),
         f"Coordinación/Comité Curricular\nNombre: {datos_g.get('aprobador') or ''}\nFecha:\nFirma:"],
    ], anchos=[0.5, 0.5])]
    return el


def _tipos(tipos: list[str]) -> str:
    nombres = {"heteroevaluacion": "Hetero", "coevaluacion": "Co", "autoevaluacion": "Auto"}
    marcas = [f"{nombres[k]} [{'x' if k in tipos else ' '}]" for k in nombres]
    return " ".join(marcas)


def construir_trazabilidad(datos: dict) -> list[Elemento]:
    """Anexo de trazabilidad: fuentes por sección, fuera del sílabo oficial (RF-43)."""
    el: list[Elemento] = [
        Titulo("ANEXO DE TRAZABILIDAD", 0),
        Parrafo(f"{datos['secciones'].get('identificacion', {}).get('nombre_pf', '')} — "
                f"periodo {datos['silabo']['periodo']}. Documento de control interno; no forma "
                "parte del sílabo entregado al estudiante.", cursiva=True),
    ]
    for clave, titulo in datos["titulos"].items():
        fuentes = datos["fuentes"].get(clave, [])
        el.append(Titulo(titulo, 2))
        if not fuentes:
            el.append(Parrafo("Datos importados de la ficha curricular o sin fuentes registradas.",
                              cursiva=True))
            continue
        filas = [["Documento", "Versión", "Página", "Fragmento"]]
        filas += [[f["documento"], f["version"], str(f["pagina"]), f["fragmento_id"]] for f in fuentes]
        el.append(Tabla(filas, anchos=[0.5, 0.15, 0.1, 0.25]))
    return el
