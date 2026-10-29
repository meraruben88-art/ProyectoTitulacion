# Informe de evaluación de SyllabusAI

Generado el 2026-10-23T03:27:26+00:00 con `syllabusai evaluar` · modelo: **simulado**.

> **Advertencia.** Las métricas automáticas se calcularon sobre el corpus y el catálogo de EJEMPLO, con el modelo simulado: prueban que el pipeline de evaluación funciona, no la calidad de redacción de Qwen3-8B. Las filas marcadas con ⚠️ salen de `eval/datos_simulados/`, que son datos **FICTICIOS** hasta el piloto con docentes.

## Resumen frente a las metas del SPEC (sección 11)

| Dimensión | Indicador | Resultado | Meta | Cumple |
|---|---|---|---|---|
| Recuperación | Recall@5 | 81,0 % | ≥ 85 % | ❌ |
| Recuperación | MRR | 0,927 | informativo | — |
| Recuperación | Consultas sin fragmentos obsoletos | 100,0 % | 100 % | ✅ |
| Fidelidad a las fuentes ⚠️ | Afirmaciones sustentadas (revisión manual) | 93,3 % | ≥ 90 % | ✅ |
| Corrección de citas | Citas a documento vigente, fragmento y página correctos | 100,0 % | ≥ 95 % | ✅ |
| Abstención | Casos sin evidencia en que el agente se abstiene | 100,0 % | ≥ 90 % | ✅ |
| Completitud | Secciones sin campos vacíos al primer intento | 100,0 % | ≥ 95 % | ✅ |
| Coherencia curricular | RA con evidencia, momento y evaluación al exportar | 100,0 % | 100 % | ✅ |
| Atención al docente | Pedidos del docente cumplidos en el sílabo final | 100,0 % | informativo | — |
| Atención al docente | Casos adversos resueltos correctamente | 100,0 % | 100 % | ✅ |
| Calidad documental ⚠️ | Rúbrica académica (1–5), asistido / manual | 4,42 / 3,42 | ≥ 4 | ✅ |
| Reducción de tiempo ⚠️ | Tiempo asistido frente a manual | −58,4 % (144 vs 347 min) | ≥ 50 % menos | ✅ |
| Esfuerzo de corrección | Distancia de edición (palabras) | 21 palabras en 1 edición(es) | informativo | — |
| Usabilidad ⚠️ | SUS | 80,0 | ≥ 70 | ✅ |
| Rendimiento técnico | Latencia media por sección | 0,071 s | ≤ 60 s | ✅ |

## Reproducibilidad de la ingesta

El corpus se ingestó desde cero en un entorno limpio: 8 documentos, 337 fragmentos, 1 documento(s) obsoleto(s), 33,0 s.

## Recuperación por consulta

Recall@5 normalizado: relevantes recuperados entre los 5 primeros, dividido por el mínimo entre 5 y los relevantes vigentes del índice. RR: inverso de la posición del primer relevante.

| ID | Consulta | Recall | RR |
|---|---|---|---|
| R01 | niveles de la rúbrica socioformativa receptivo resolutivo reflexivo crítico cocreativo | 0,80 | 1,00 |
| R02 | metacompetencias transversales institucionales del proyecto formativo | 1,00 | 1,00 |
| R03 | ejes transversales del modelo educativo que se declaran en el sílabo | 0,60 | 1,00 |
| R04 | cómo redactar la pregunta reto y el producto integrador | 1,00 | 1,00 |
| R05 | control obligatorio de horas por componente de aprendizaje | 1,00 | 1,00 |
| R06 | planeación operativa por momentos macro-fases del proyecto formativo | 0,80 | 1,00 |
| R07 | oportunidad de mejora y reentrega de las evidencias evaluadas | 0,25 | 1,00 |
| R08 | datos personales que no se ingresan en herramientas de inteligencia artificial | 1,00 | 1,00 |
| R09 | declaración del uso de inteligencia artificial en cada evidencia | 0,33 | 1,00 |
| R10 | PE-PP-04 | 1,00 | 1,00 |
| R11 | PE-MI-06 normas y estándares de calidad | 1,00 | 1,00 |
| R12 | contenidos mínimos de Bases de Datos | 1,00 | 1,00 |
| R13 | resultados de aprendizaje de Inteligencia Artificial | 1,00 | 1,00 |
| R14 | bibliografía básica de Ingeniería de Software | 1,00 | 1,00 |
| R15 | contenidos mínimos de Desarrollo de Aplicaciones Web | 1,00 | 1,00 |
| R16 | resultados de aprendizaje de Redes de Computadoras | 1,00 | 1,00 |
| R17 | ITI-405 horas de contacto docente y prerrequisitos | 1,00 | 1,00 |
| R18 | ejemplo de planeación por momentos de un sílabo aprobado | 0,67 | 1,00 |
| R19 | aporte del proyecto formativo al PIS sin horas adicionales | 1,00 | 1,00 |
| R20 | accesibilidad e inclusión de estudiantes con necesidades educativas específicas | 1,00 | 1,00 |
| R21 | principios de la gobernanza ética de la inteligencia artificial | 0,20 | 0,25 |
| R22 | formulación del problema del proyecto interdisciplinario socioformativo | 0,00 | 0,00 |
| R23 | confirmar la competencia específica del perfil de egreso a la que contribuye el PF | 1,00 | 1,00 |
| R24 | seguimiento, mejora continua y aseguramiento de la calidad | 0,80 | 1,00 |

## Casos piloto: ¿el agente hizo lo que pidió el docente?

### P1 · ITI-501 — 10/10 verificaciones

- **Docente (anclaje_curricular):** fortalecer el pensamiento crítico
  - **Agente:** Entendí: habilidad blanda: Pensamiento crítico. Ya lo apliqué en esta propuesta.
- **Docente (planeacion_momentos):** momento 3 con 30% y momento 1 con 25%
  - **Agente:** Entendí: peso del momento 3: 30 %; peso del momento 1: 25 %. Ya lo apliqué en esta propuesta. Lo tendré en cuenta en: 7.7 Sistema de evaluación socioformativa.
- **Docente (evaluacion):** agrega el criterio: el asistente responde correctamente al menos el 80 % de las preguntas de prueba
  - **Agente:** Entendí: agregar el criterio «El asistente responde correctamente al menos el 80 % de las preguntas de prueba». Ya lo apliqué en esta propuesta.
- **Docente (recursos):** agrega la referencia: Jurafsky, D., & Martin, J. H. (2024). Speech and Language Processing (3rd ed. draft). Stanford University.
  - **Agente:** Entendí: agregar a la bibliografía «Jurafsky, D., & Martin, J. H. (2024). Speech and Language Processing (3rd ed. draft). Stanford University.». Ya lo apliqué en esta propuesta.
- Exportados: P1_silabo_ITI-501_B26_1.docx, P1_silabo_ITI-501_B26_1.pdf

### P2 · ITI-302 — 8/8 verificaciones

- **Docente (problema_reto):** el escenario será la secretaría académica de la sede Ambato
  - **Agente:** Entendí: escenario: La secretaría académica de la sede Ambato. Ya lo apliqué en esta propuesta. Lo tendré en cuenta en: 7.6 Planeación operativa por momentos; 7.8 Recursos, bibliografía y escenarios. También afecta a secciones ya aprobadas (7.2 Anclaje curricular y contribución al perfil de egreso): reábralas al final si quiere aplicarlo allí.
- **Docente (contenidos):** hazlo más breve
  - **Agente:** Entendí: redacción más breve. Ya lo apliqué en esta propuesta.
- **Docente (planeacion_momentos):** usa aula invertida
  - **Agente:** Entendí: metodología: Aula invertida. Ya lo apliqué en esta propuesta.
- **Docente (seguimiento_mejora):** (edita a mano: acciones_mejora)
  - **Agente:** Edición guardada y validada.
- Exportados: P2_silabo_ITI-302_B26_2.docx, P2_silabo_ITI-302_B26_2.pdf

### P3 · ITI-403 — 8/8 verificaciones

- **Docente (problema_reto):** el reto debe tratar sobre la gestión de turnos del centro de salud universitario
  - **Agente:** Entendí: tema del reto: La gestión de turnos del centro de salud universitario. Ya lo apliqué en esta propuesta. Lo tendré en cuenta en: 7.4 Resultados de aprendizaje y evidencias; 7.6 Planeación operativa por momentos. También afecta a secciones ya aprobadas (7.2 Anclaje curricular y contribución al perfil de egreso): reábralas al final si quiere aplicarlo allí.
- **Docente (planeacion_momentos):** agrega autoevaluación y coevaluación
  - **Agente:** Entendí: incluir coevaluacion; incluir autoevaluacion. Ya lo apliqué en esta propuesta.
- **Docente (seguimiento_mejora):** más detallado
  - **Agente:** Entendí: redacción más detallada. Ya lo apliqué en esta propuesta.
- Exportados: P3_silabo_ITI-403_B26_3.docx, P3_silabo_ITI-403_B26_3.pdf

### P4 · ITI-604 — 8/8 verificaciones

- **Docente (anclaje_curricular):** agrega el eje de territorialización
  - **Agente:** Entendí: eje: Territorialización, innovación y emprendimiento disruptivo. Ya lo apliqué en esta propuesta.
- **Docente (planeacion_momentos):** momento 2 con 25%
  - **Agente:** Entendí: peso del momento 2: 25 %. Ya lo apliqué en esta propuesta. Lo tendré en cuenta en: 7.7 Sistema de evaluación socioformativa.
- Exportados: P4_silabo_ITI-604_B26_4.docx, P4_silabo_ITI-604_B26_4.pdf

### P5 · ITI-405 — 6/6 verificaciones

- **Docente (resultados_aprendizaje):** cambia el RA2 para que sea más corto
  - **Agente:** «cambia el RA2 para que sea más corto»: los RA, los contenidos mínimos, las horas, los créditos, la competencia del perfil y los prerrequisitos son datos oficiales de la malla; no se modifican en el sílabo. Si hace falta cambiarlos, escálelo al Comité Curricular.
- **Docente (planeacion_momentos):** enfócate en la seguridad de la red
  - **Agente:** Entendí: énfasis en la seguridad de la red. Ya lo apliqué en esta propuesta.
- Exportados: P5_silabo_ITI-405_B26_5.docx, P5_silabo_ITI-405_B26_5.pdf

## Casos adversos

| ID | Caso | Correcto | Respuesta del agente |
|---|---|---|---|
| A1 | El docente no describe el problema del territorio; la sección 7.3 debe abstenerse. | ✅ | No redacté la sección: faltan datos requeridos: contexto_problema. Puede darme lo que falta aquí mismo, por ejemplo: «El problema es que … (fuente: …)», o completar la sección usted. |
| A2 | El perfil de egreso está obsoleto; el anclaje curricular debe abstenerse. | ✅ | No redacté la sección: no hay evidencia suficiente en documentos vigentes de tipo: perfil_egreso. Cargue o marque como vigentes esos documentos. Puede completar la sección usted o pedir al administrador del corpus que ca |
| A3 | Asignatura de una carrera sin perfil ni malla en el corpus (información ausente). | ✅ | No redacté la sección: no hay evidencia suficiente en documentos vigentes de tipo: perfil_egreso. Cargue o marque como vigentes esos documentos. Puede completar la sección usted o pedir al administrador del corpus que ca |
| A4 | El modelo cita un fragmento que no recibió e inventa una referencia; ambos se descartan. | ✅ |  |
| A5 | El docente pide pesos que no suman 100 %; se mantienen los sugeridos y se avisa. | ✅ | Entendí: peso del momento 1: 80 %; peso del momento 2: 30 %. Los pesos pedidos (momento 1: 80 %, momento 2: 30 %) no permiten sumar 100 %; se mantienen los sugeridos. No los guardé. |
| A6 | El docente pide eliminar un RA oficial; el agente lo rechaza y conserva el RA. | ✅ | «elimina el RA3»: los RA, los contenidos mínimos, las horas, los créditos, la competencia del perfil y los prerrequisitos son datos oficiales de la malla; no se modifican en el sílabo. Si hace falta cambiarlos, escálelo  |

## Datos de usuarios (FICTICIOS)

- Tiempo medio manual: 347 min; asistido: 144 min.
- SUS por docente: 80,00; 82,50; 67,50; 82,50; 87,50.
- Rúbrica de calidad (pertinencia, coherencia_curricular, claridad, ajuste_al_formato): asistido 4,42, manual 3,42.
- Fidelidad: 30 afirmaciones revisadas.
