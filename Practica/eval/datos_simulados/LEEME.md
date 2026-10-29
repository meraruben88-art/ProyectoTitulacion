# Datos simulados de la validación con docentes — FICTICIOS

Estos archivos **no son mediciones reales**. Se inventaron para construir y probar el pipeline de
evaluación (`syllabusai evaluar`) antes del piloto con docentes (fase 8 del plan). Sirven como
plantilla: en el piloto real se reemplazan por los datos recogidos, con las mismas columnas.

| Archivo | Qué registra | Dimensión del SPEC (sección 11) |
|---|---|---|
| `tiempos_EJEMPLO.csv` | Minutos que tardó cada docente en elaborar el sílabo, a mano y con el agente | Reducción de tiempo |
| `sus_EJEMPLO.csv` | Respuestas (1–5) al cuestionario SUS de 10 ítems | Usabilidad |
| `rubrica_calidad_EJEMPLO.csv` | Puntuación (1–5) de expertos curriculares por criterio, a ciegas sobre el método | Calidad documental |
| `fidelidad_EJEMPLO.csv` | Revisión manual de afirmaciones del sílabo frente a los fragmentos citados | Fidelidad a las fuentes |

Diseño previsto: cinco docentes (D1–D5), una asignatura piloto cada uno; cada docente elabora
el sílabo de su asignatura a mano (periodo anterior, cronometrado) y con el agente.
