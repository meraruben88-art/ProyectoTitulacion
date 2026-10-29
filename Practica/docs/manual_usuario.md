# Manual de usuario — SyllabusAI

SyllabusAI le ayuda a elaborar el sílabo de un Proyecto Formativo (PF) en el formato
institucional UTI 2026. El agente redacta cada sección con la ficha curricular, los documentos
institucionales y lo que usted le pida. Usted revisa, corrige y aprueba. **Nada se exporta sin su
aprobación.**

> Con el modelo **simulado** (el que viene por defecto, sin GPU) las propuestas salen de
> plantillas y el agente solo entiende ciertos tipos de pedido (ver la tabla de la sección 4). Con
> el modelo real (Qwen3-8B en la A100) el agente entiende cualquier texto.

## 1. Ingreso

Abra `http://localhost:8501` e ingrese con su correo y contraseña institucionales. En el
prototipo hay dos usuarios de ejemplo:

| Rol | Correo | Contraseña |
|---|---|---|
| Docente | `docente@uti.ejemplo` | `docente123` |
| Administrador del corpus | `admin@uti.ejemplo` | `admin123` |

## 2. Crear un sílabo («Nuevo sílabo»)

1. **Elija el Proyecto Formativo.** Se muestran, bloqueados 🔒, los datos que vienen de la malla:
   horas, resultados de aprendizaje (RA) y contenidos mínimos. El sílabo no puede cambiarlos.
2. **Datos generales.** Periodo, semanas y, sobre todo, el **problema del territorio con datos y
   sus fuentes**. El agente no inventa datos del territorio: si deja este campo vacío, la sección
   7.3 se detiene y le pide la información (puede dársela después, en la conversación).
3. **¿Cómo quiere su sílabo?** Todo es opcional:
   - qué construirán los estudiantes (producto integrador) y el tema del reto;
   - metodología (ABP, aula invertida, Scrum…), modalidad de trabajo (individual, parejas,
     equipos de N);
   - tecnologías o software;
   - uso de IA por los estudiantes: *permitida* (con declaración), *limitada* (solo para explorar
     alternativas) o *prohibida* («No aplica» en cada momento);
   - tipos e instrumento de evaluación; habilidades blandas;
   - bibliografía que usted propone (el agente solo cita la malla, los documentos del corpus y lo
     que usted escriba aquí).
4. **Otras indicaciones (texto libre).** Por ejemplo: «Que trabajen en equipos de 3, momento 3
   con 30 %, énfasis en la ética de los datos».
5. Pulse **Crear sílabo e iniciar el agente**.

## 3. Revisar sección por sección

La pantalla «Revisión» muestra la sección que el agente está esperando que usted revise.

- **Izquierda: la propuesta.** Puede editar cualquier campo que no esté marcado 🔒 oficial, o
  activar «Editar como JSON».
  - **✅ Aprobar y continuar**: aprueba (con sus cambios, si los hizo) y el agente redacta la
    sección siguiente. Verá en vivo lo que hace: busca evidencia, redacta y valida.
  - **💾 Guardar edición**: guarda su versión y la valida sin avanzar.
- **Derecha, pestaña 💬 Conversación con el agente.** Escriba lo que quiere cambiar. El agente
  responde qué entendió, qué aplicó en esta sección, qué recordará para las siguientes y qué no
  puede hacer (por ejemplo, modificar un RA oficial).
- **Pestaña ⚠️ Alertas.** Los hallazgos **bloqueantes** (⛔) impiden exportar y deben corregirse.
  Las **advertencias** (⚠️) puede descartarlas con una justificación.
- **Pestaña 📄 Fuentes.** Los fragmentos de documentos que sustentan la propuesta, con
  documento, versión y página.
- **Barra lateral, 🧠 Lo que el agente recuerda.** Sus preferencias vigentes. Con «✏️ Editar
  preferencias» las cambia a mano; rigen desde la próxima propuesta.

Si una sección aparece como **⚠️ abstenida**, el agente no encontró evidencia suficiente o le
falta un dato suyo. Lea su respuesta en la conversación: le dirá qué falta. Puede dárselo ahí
mismo, completar la sección usted o pedir al administrador que cargue el documento.

## 4. Qué le puede pedir al agente

| Quiere… | Escriba, por ejemplo |
|---|---|
| Fijar el producto | «el producto será un chatbot para la biblioteca» · «que desarrollen una app de turnos» |
| Fijar el tema del reto | «el reto debe tratar sobre la deserción estudiantil» |
| Dar el problema del territorio | «El problema es que el 40 % de las consultas llegan fuera de horario (fuente: informe 2025)» |
| Cambiar el escenario o los actores | «el escenario será la cooperativa San Francisco» · «los actores son los socios» |
| Modalidad de trabajo | «en equipos de 3» · «en parejas» · «trabajo individual» |
| Política de IA | «sin IA» · «limita la IA» · «permite la IA» |
| Tecnologías | «usa Python y scikit-learn» · «sin Docker» |
| Metodología | «usa aula invertida» · «con Scrum» · «design thinking» |
| Evaluación | «agrega coevaluación» · «sin autoevaluación» · «evalúa con lista de cotejo» |
| Pesos por momento | «momento 3 con 30 %» (el resto se reparte hasta 100 %) |
| Criterio de evaluación | «agrega el criterio: el prototipo responde en menos de 2 s» |
| Bibliografía propia | «agrega la referencia: Autor, A. (2024). Título. Editorial.» |
| Habilidades, metacompetencia, ejes | «fortalecer el liderazgo» · «metacompetencia de innovación» · «agrega el eje de interculturalidad» |
| Ajustar la redacción | «más breve» · «más detallado» · «énfasis en la práctica» |

Lo que el agente **no hace**: cambiar RA, contenidos mínimos, horas, créditos, prerrequisitos o la
competencia del perfil (son de la malla aprobada; se escalan al Comité Curricular), inventar
datos del territorio o bibliografía, ni citar documentos obsoletos.

## 5. Verificación final y exportación

Cuando aprueba la última sección, el agente verifica el sílabo completo (estructura,
completitud, trazabilidad, coherencia RA–momento–evaluación, horas y pesos). Si hay hallazgos
bloqueantes, elija la sección y pulse **Reabrir sección**. Si no los hay, pulse **Generar DOCX**
o **Generar PDF** y descargue el archivo. Junto al DOCX se genera un **anexo de trazabilidad**
con las fuentes de cada sección.

## 6. Administración del corpus (rol administrador)

En «Corpus» se ven los documentos con su versión, tipo, carrera, vigencia y número de fragmentos.

- **Cargar documento:** PDF o DOCX con título, tipo, carrera (TODAS si es institucional), versión
  y fecha de vigencia. Se indexa en el mismo paso.
- Una versión nueva del mismo documento deja **obsoleta** la anterior; no se borra. El agente
  nunca cita documentos obsoletos.
- **Marcar vigente / obsoleto** cambia la vigencia a mano.
- «Buscar» permite consultar directamente el recuperador.
