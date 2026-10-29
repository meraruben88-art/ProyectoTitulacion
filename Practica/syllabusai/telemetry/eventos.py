"""Instrumentación: eventos, esfuerzo de corrección y métricas del servidor (RF-50 a RF-54)."""

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from syllabusai.db.modelos import Evento


def registrar(
    sesion: Session,
    tipo: str,
    *,
    silabo_id: int | None = None,
    paso: str | None = None,
    latencia_ms: float | None = None,
    ttft_ms: float | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    payload: dict[str, Any] | None = None,
) -> Evento:
    evento = Evento(
        tipo=tipo, silabo_id=silabo_id, paso=paso, latencia_ms=latencia_ms, ttft_ms=ttft_ms,
        tokens_in=tokens_in, tokens_out=tokens_out, payload=payload or {},
    )
    sesion.add(evento)
    sesion.flush()
    return evento


def distancia_edicion(a: str, b: str) -> int:
    """Distancia de Levenshtein por palabras entre lo propuesto y lo aprobado (RF-51)."""
    x, y = a.split(), b.split()
    previa = list(range(len(y) + 1))
    for i, palabra in enumerate(x, start=1):
        actual = [i]
        for j, otra in enumerate(y, start=1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (palabra != otra)))
        previa = actual
    return previa[-1]


def texto_plano(contenido: Any) -> str:
    """Aplana el JSON de una sección para comparar versiones palabra por palabra."""
    if isinstance(contenido, dict):
        return " ".join(texto_plano(v) for v in contenido.values())
    if isinstance(contenido, list):
        return " ".join(texto_plano(v) for v in contenido)
    return "" if contenido is None else str(contenido)


_COLUMNAS = ["id", "fecha", "silabo_id", "tipo", "paso", "latencia_ms", "ttft_ms",
             "tokens_in", "tokens_out", "payload"]


def exportar(sesion: Session, directorio: Path, desde: datetime | None = None) -> tuple[Path, Path]:
    """Escribe los eventos en CSV y JSON para el análisis de resultados (RF-54)."""
    consulta = select(Evento).order_by(Evento.id)
    if desde is not None:
        consulta = consulta.where(Evento.fecha >= desde)
    filas = [
        {
            "id": e.id, "fecha": e.fecha.isoformat(), "silabo_id": e.silabo_id, "tipo": e.tipo,
            "paso": e.paso, "latencia_ms": e.latencia_ms, "ttft_ms": e.ttft_ms,
            "tokens_in": e.tokens_in, "tokens_out": e.tokens_out, "payload": e.payload,
        }
        for e in sesion.scalars(consulta)
    ]
    directorio.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    ruta_json = directorio / f"eventos-{marca}.json"
    ruta_csv = directorio / f"eventos-{marca}.csv"
    ruta_json.write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
    with ruta_csv.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=_COLUMNAS)
        escritor.writeheader()
        for fila in filas:
            escritor.writerow(fila | {"payload": json.dumps(fila["payload"], ensure_ascii=False)})
    return ruta_csv, ruta_json


# Métricas Prometheus de vLLM relevantes para RF-53. Los nombres cambian entre versiones de
# vLLM, por eso se buscan por prefijo y se devuelven todas las que coincidan.
_PREFIJOS_VLLM = (
    "vllm:gpu_cache_usage_perc", "vllm:kv_cache_usage_perc", "vllm:num_requests_running",
    "vllm:num_requests_waiting", "vllm:prompt_tokens_total", "vllm:generation_tokens_total",
)
_LINEA = re.compile(r"^([a-zA-Z_:][\w:]*)(\{[^}]*\})?\s+([-+0-9.eE]+|NaN)$")


def leer_metricas_vllm(url: str, timeout: float = 5.0) -> dict[str, float]:
    respuesta = httpx.get(url, timeout=timeout)
    respuesta.raise_for_status()
    metricas = {}
    for linea in respuesta.text.splitlines():
        coincidencia = _LINEA.match(linea.strip())
        if coincidencia and coincidencia.group(1).startswith(_PREFIJOS_VLLM):
            metricas[coincidencia.group(1)] = float(coincidencia.group(3))
    return metricas
