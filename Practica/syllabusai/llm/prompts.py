"""Instrucciones para el modelo generador (versionadas junto con el código, RNF-05)."""

import json
from typing import Any

from pydantic import BaseModel, create_model

from syllabusai.formato.catalogos import EJES, HABILIDADES_BLANDAS, METACOMPETENCIAS
from syllabusai.formato.definicion import DefinicionSeccion
from syllabusai.formato.esquemas import ESQUEMAS

VERSION_PROMPTS = "2026.10-2"

SISTEMA = """Eres SyllabusAI, asistente de la Universidad Tecnológica Indoamérica para elaborar \
sílabos de Proyecto Formativo (PF) en el formato institucional 2026, conforme al Modelo \
Educativo Institucional 2026 y a la taxonomía socioformativa.

Reglas obligatorias:
1. Usa ÚNICAMENTE la información de la ficha curricular, de los datos del docente y de los \
fragmentos de evidencia. No inventes normativa, cifras, datos del territorio ni bibliografía.
2. Los datos marcados como oficiales (RA, contenidos mínimos, horas, competencia del perfil) se \
transcriben exactamente; nunca se reescriben.
3. En "fuentes" pon los identificadores [id] de los fragmentos que realmente sustentan lo que \
escribiste. No cites fragmentos que no usaste ni identificadores que no aparecen.
4. Si la evidencia no alcanza para redactar la sección con fidelidad, no la redactes: escribe en \
"abstencion" qué información falta y deja el contenido con sus valores vacíos.
5. Redacta en español formal, con verbos de desempeño de mediana o alta complejidad; evita \
«conocer», «comprender» y formulaciones puramente temáticas.
6. Respeta las preferencias del docente (producto, metodología, modalidad de trabajo, tecnologías, \
política de IA, evaluación, bibliografía propia) y su indicación para esta versión, salvo que \
contradigan los datos oficiales: en ese caso conserva lo oficial y explícalo en "notas".
7. En "notas" explica al docente, en una a tres frases, qué hiciste con su indicación. Si no hubo \
indicación, deja "notas" en null.
8. Responde solo con un objeto JSON que cumpla el esquema indicado."""


def esquema_salida(clave: str) -> type[BaseModel]:
    return create_model(
        f"Salida_{clave}",
        contenido=(ESQUEMAS[clave], ...),
        fuentes=(list[str], []),
        abstencion=(str | None, None),
        notas=(str | None, None),
    )


def _bloque_fragmentos(fragmentos: list[dict[str, Any]]) -> str:
    if not fragmentos:
        return "(no se recuperaron fragmentos)"
    partes = []
    for f in fragmentos:
        ruta = " > ".join(f["ruta"]) if f["ruta"] else "—"
        partes.append(
            f"[{f['id']}] {f['titulo']} (tipo {f['tipo']}, versión {f['version']}, "
            f"p. {f['pagina']}) — {ruta}\n{f['texto']}"
        )
    return "\n\n".join(partes)


def _json(datos: Any) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=2)


def construir_mensajes(definicion: DefinicionSeccion, contexto: dict[str, Any]) -> list[dict]:
    asignatura = contexto["asignatura"]
    partes = [
        f"Sección a redactar: {definicion.numero} {definicion.titulo} (clave «{definicion.clave}»).",
        f"Instrucciones de la sección:\n{definicion.instrucciones.strip()}",
        (f"Proyecto Formativo: {asignatura['nombre']} ({asignatura['codigo']}), carrera "
         f"{asignatura['carrera']}, nivel {asignatura['nivel']}."),
        f"Ficha curricular oficial (no modificar):\n{_json(contexto['ficha'])}",
        f"Datos registrados por el docente:\n{_json(contexto['datos_generales'])}",
    ]
    if contexto.get("aprobadas"):
        partes.append(f"Secciones ya aprobadas por el docente:\n{_json(contexto['aprobadas'])}")
    if contexto.get("esqueleto_momentos") and definicion.clave == "planeacion_momentos":
        partes.append(
            "Esqueleto de momentos calculado (respeta números, semanas, RA y pesos):\n"
            + _json(contexto["esqueleto_momentos"])
        )
    if contexto.get("esqueleto_evaluacion") and definicion.clave == "evaluacion":
        partes.append(
            "Evidencias evaluadas que fija la planeación (respeta momento, RA y peso):\n"
            + _json(contexto["esqueleto_evaluacion"])
        )
    if definicion.clave == "anclaje_curricular":
        partes.append("Metacompetencias institucionales (elige de esta lista):\n- "
                      + "\n- ".join(METACOMPETENCIAS))
        partes.append("Ejes del Modelo Educativo (denominación exacta):\n- " + "\n- ".join(EJES))
        partes.append("Habilidades blandas sugeridas:\n- " + "\n- ".join(HABILIDADES_BLANDAS))
    if definicion.clave == "recursos":
        candidatos = contexto.get("candidatos_bibliografia") or []
        partes.append("Bibliografía candidata (usa solo estas):\n- " + "\n- ".join(candidatos)
                      if candidatos else "Bibliografía candidata: ninguna.")
    preferencias = {k: v for k, v in (contexto.get("preferencias") or {}).items() if v}
    if preferencias:
        partes.append("Preferencias del docente para todo el sílabo (respétalas):\n"
                      + _json(preferencias))
    local = {k: v for k, v in (contexto.get("local") or {}).items() if v}
    if local:
        partes.append("Ajustes pedidos para esta sección (énfasis, extensión, criterios):\n"
                      + _json(local))
    if contexto.get("indicacion"):
        partes.append("Indicación del docente para esta versión (texto original): "
                      f"{contexto['indicacion']}")
    partes.append(f"Fragmentos de evidencia:\n{_bloque_fragmentos(contexto.get('fragmentos', []))}")
    partes.append('Devuelve {"contenido": {...}, "fuentes": ["id", ...], "abstencion": null, '
                  '"notas": null}.')
    return [
        {"role": "system", "content": SISTEMA},
        {"role": "user", "content": "\n\n".join(partes)},
    ]
