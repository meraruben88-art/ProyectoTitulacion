/* Utilidades de DOM y editor genérico de contenido estructurado.

   El contenido de cada sección del sílabo, del PIS y de las fichas curriculares es JSON
   validado en el servidor. El editor lo dibuja tal como viene (textos, números, listas de
   textos, listas de objetos, objetos anidados) y lo devuelve con la misma forma con `leer()`.
   Los campos oficiales se muestran bloqueados; `desbloquear()` los habilita. */

"use strict";

function h(etiqueta, atributos, ...hijos) {
  const el = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(atributos || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "clase") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "estilo") el.setAttribute("style", v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const hijo of hijos.flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
  return el;
}

const ETIQUETAS = {
  nombre_pf: "Nombre del Proyecto Formativo", codigo: "Código", version: "Versión", facultad: "Facultad",
  carrera: "Carrera", nivel: "Nivel", modalidad: "Modalidad", unidad_organizacion: "Unidad de organización curricular",
  periodo_academico: "Periodo académico", creditos: "Créditos", horas_contacto: "Horas de contacto docente",
  horas_practicas: "Horas práctico-experimentales", horas_autonomas: "Horas autónomas", total_horas: "Total de horas",
  prerrequisitos: "Prerrequisitos", correquisitos: "Correquisitos", docente: "Docente", correo_docente: "Correo del docente",
  competencia_especifica: "Competencia específica del perfil", desempeno_central: "Desempeño profesional central",
  metacompetencia: "Metacompetencia", metacompetencia_secundaria: "Metacompetencia secundaria",
  habilidades_blandas: "Habilidades blandas", ejes: "Ejes del Modelo Educativo", eje: "Eje", justificacion: "Justificación",
  accesibilidad_nee: "Accesibilidad y NEE", articulacion_pf: "Articulación con otros PF", pis_periodo: "PIS del periodo",
  aporte_pis: "Aporte al PIS", microcredencial: "Microcredencial", problema: "Problema", pregunta_reto: "Pregunta reto",
  producto_integrador: "Producto integrador", escenario_actores: "Escenario y actores", criterio_impacto: "Criterio de impacto",
  resultados: "Resultados de aprendizaje", enunciado: "Enunciado", evidencia: "Evidencia", momentos: "Momentos",
  contenidos_minimos: "Contenidos mínimos (oficiales)", conceptuales: "Conceptuales (saber conocer)",
  procedimentales: "Procedimentales (saber hacer)", actitudinales: "Actitudinales (saber ser y convivir)",
  numero: "Número", nombre: "Nombre", semanas: "Semanas", ra: "RA", proposito: "Propósito",
  contacto_docente: "Contacto docente", aprendizaje_autonomo: "Aprendizaje autónomo",
  practico_experimental: "Práctico-experimental", evidencia_parcial: "Evidencia parcial",
  contenidos_conceptuales: "Contenidos conceptuales", contenidos_procedimentales: "Contenidos procedimentales",
  contenidos_actitudinales: "Contenidos actitudinales", politica_ia: "Política de uso de IA", evaluacion: "Evaluación",
  peso: "Peso (%)", tipos: "Tipos de evaluación", instrumento: "Instrumento", retroalimentacion: "Retroalimentación",
  recursos: "Recursos", momento: "Momento", criterios: "Criterios de desempeño", oportunidad_mejora: "Oportunidad de mejora",
  evidencias: "Evidencias evaluadas", bibliografia_basica: "Bibliografía básica",
  bibliografia_complementaria: "Bibliografía complementaria", bases_datos: "Bases de datos", tecnologia_ia: "Tecnología e IA",
  escenarios: "Escenarios", accesibilidad: "Accesibilidad", registro_logro_ra: "Registro del logro de los RA",
  acciones_mejora: "Acciones de mejora", ajustes_siguiente_periodo: "Ajustes para el siguiente periodo",
  cambios_a_escalar: "Cambios a escalar al Comité Curricular",
  // PIS
  titulo: "Título del PIS", periodo: "Periodo", equipo_docente: "Equipo docente", contexto: "Contexto o territorio",
  delimitacion: "Delimitación", competencias: "Competencias que moviliza", pf_participantes: "PF participantes",
  articulacion: "Matriz de articulación", competencia: "Competencia (del perfil)", pf: "PF", rap: "RAP", aporte: "Aporte al PIS",
  aporte_este_pf: "Aporte de este PF al PIS", evidencia_integradora: "Evidencia integradora",
  aportes_integrados: "¿Qué aportes de los PF integra?", criterios_logro: "Criterios de logro", investigacion: "Diseño de la investigación",
  pregunta: "Pregunta de indagación", enfoque: "Enfoque o método", fuentes_tecnicas: "Fuentes, datos o técnicas",
  hallazgos_esperados: "Hallazgos que fundamentan la propuesta", etapas: "Secuencia de la actuación", etapa: "Etapa",
  actuacion: "Actuación de los estudiantes", aporte_pf: "Aporte de los PF", resultado: "Resultado que alimenta la etapa siguiente",
  cronograma: "Plan de actividades y cronograma", semana: "Semana", actividad: "Actividad", pf_rap: "PF / RAP",
  responsable: "Responsable", roles: "Roles y responsabilidades", actor: "Actor", responsabilidades: "Responsabilidades",
  socializacion: "Socialización", reflexion: "Reflexión y mejora", impacto: "Resultados e impacto esperado",
  prueba_interdisciplinariedad: "Prueba de interdisciplinariedad",
  // ficha curricular
  resultados_aprendizaje: "Resultados de aprendizaje", bibliografia: "Bibliografía de la ficha",
  desempeno: "Desempeño", pagina_ces: "Página en el PDF del CES",
};

function etiquetaDe(clave) {
  if (ETIQUETAS[clave]) return ETIQUETAS[clave];
  const t = String(clave).replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function autoAltura(area) {
  const ajustar = () => { area.style.height = "auto"; area.style.height = Math.min(area.scrollHeight + 2, 520) + "px"; };
  area.addEventListener("input", ajustar);
  requestAnimationFrame(ajustar);
}

function vacioComo(muestra) {
  if (Array.isArray(muestra)) return [];
  if (muestra && typeof muestra === "object") {
    const o = {};
    for (const [k, v] of Object.entries(muestra)) o[k] = vacioComo(v);
    return o;
  }
  if (typeof muestra === "number") return 0;
  if (typeof muestra === "boolean") return false;
  return "";
}

/* Valor vacío a partir de un JSON Schema de Pydantic (para añadir el primer elemento de una lista). */
function vacioDeEsquema(esquema, defs) {
  if (!esquema) return "";
  if (esquema.$ref) return vacioDeEsquema(defs[esquema.$ref.split("/").pop()], defs);
  if (esquema.anyOf) return vacioDeEsquema(esquema.anyOf.find((x) => x.type !== "null") || {}, defs);
  if (esquema.type === "object" && esquema.properties) {
    const o = {};
    for (const [k, v] of Object.entries(esquema.properties)) o[k] = vacioDeEsquema(v, defs);
    return o;
  }
  if (esquema.type === "array") return [];
  if (esquema.type === "integer" || esquema.type === "number") return 0;
  if (esquema.type === "boolean") return false;
  return "";
}

function subEsquema(esquema, clave, defs) {
  if (!esquema) return null;
  let e = esquema;
  if (e.$ref) e = defs[e.$ref.split("/").pop()];
  if (e && e.anyOf) e = e.anyOf.find((x) => x.type !== "null") || e;
  if (e && e.$ref) e = defs[e.$ref.split("/").pop()];
  if (clave === "[]") return e && e.items ? e.items : null;
  return e && e.properties ? e.properties[clave] : null;
}

/* Crea un editor. opciones: { oficiales: ["campo", "*"], esquema, soloLectura, alCambiar } */
function crearEditor(valor, opciones = {}) {
  const defs = (opciones.esquema && opciones.esquema.$defs) || {};
  const oficiales = new Set(opciones.oficiales || []);
  const controles = []; // [elemento, esOficial]
  let desbloqueado = false;

  function registrar(el, oficial) {
    controles.push([el, oficial]);
    el.disabled = opciones.soloLectura || (oficial && !desbloqueado);
    if (opciones.alCambiar) el.addEventListener("input", opciones.alCambiar);
    return el;
  }

  function esOficial(ruta) {
    if (oficiales.has("*")) return true;
    return ruta.some((p) => oficiales.has(p));
  }

  function nodo(v, ruta, esquema) {
    const clave = ruta[ruta.length - 1];
    const oficial = esOficial(ruta.filter((p) => typeof p === "string"));
    if (Array.isArray(v)) return lista(v, ruta, esquema, oficial);
    if (v && typeof v === "object") return objeto(v, ruta, esquema);
    const tipo = esquema && (esquema.type || (esquema.anyOf && (esquema.anyOf.find((x) => x.type !== "null") || {}).type));
    if (typeof v === "number" || tipo === "integer" || tipo === "number") {
      const input = registrar(h("input", { type: "number", value: v ?? 0, step: "1" }), oficial);
      return { el: input, leer: () => (input.value === "" ? 0 : Number(input.value)) };
    }
    if (typeof v === "boolean") {
      const input = registrar(h("input", { type: "checkbox" }), oficial);
      input.checked = v;
      return { el: input, leer: () => input.checked };
    }
    const texto = v === null || v === undefined ? "" : String(v);
    const area = registrar(h("textarea", { rows: texto.length > 160 ? 4 : 2, "aria-label": etiquetaDe(clave) }), oficial);
    area.value = texto;
    autoAltura(area);
    const eraNulo = v === null;
    return { el: area, leer: () => (eraNulo && area.value.trim() === "" ? null : area.value) };
  }

  function campo(clave, editor, oficial) {
    return h("div", { clase: "editor-campo" + (oficial ? " oficial" : "") },
      h("div", { clase: "etiqueta" }, h("span", {}, etiquetaDe(clave)), oficial ? h("span", { clase: "candado" }, "🔒 dato oficial") : null),
      editor.el);
  }

  function objeto(v, ruta, esquema) {
    const hijos = {};
    const cont = h("div", {});
    for (const [k, sub] of Object.entries(v)) {
      const e = nodo(sub, [...ruta, k], subEsquema(esquema, k, defs));
      hijos[k] = e;
      const oficial = esOficial([...ruta, k].filter((p) => typeof p === "string"));
      if (sub && typeof sub === "object" && !Array.isArray(sub)) {
        cont.append(h("div", { clase: "editor-grupo" }, h("div", { clase: "titulo-grupo" }, etiquetaDe(k)), e.el));
      } else {
        cont.append(campo(k, e, oficial && !Array.isArray(sub)));
      }
    }
    return { el: cont, leer: () => Object.fromEntries(Object.entries(hijos).map(([k, e]) => [k, e.leer()])) };
  }

  function lista(v, ruta, esquema, oficial) {
    const clave = ruta[ruta.length - 1];
    const esquemaItem = subEsquema(esquema, "[]", defs);
    const deObjetos = v.length ? typeof v[0] === "object" && v[0] !== null : esquemaItem && (esquemaItem.$ref || esquemaItem.type === "object");
    const deNumeros = v.length ? typeof v[0] === "number" : esquemaItem && esquemaItem.type === "integer";
    const items = [];
    const cont = h("div", {});
    const lista = h("div", {});
    const bloqueadoLista = () => opciones.soloLectura || (oficial && !desbloqueado);

    function agregar(valorItem, alFinal = true) {
      const registro = {};
      if (deObjetos) {
        const e = objeto(valorItem, [...ruta, items.length], esquemaItem);
        const quitar = h("button", { type: "button", clase: "boton texto chico", title: "Quitar", onclick: () => { lista.removeChild(caja); items.splice(items.indexOf(registro), 1); opciones.alCambiar && opciones.alCambiar(); } }, "Quitar");
        registrar(quitar, oficial);
        const titulo = valorItem.codigo || valorItem.eje || valorItem.etapa || valorItem.actor || (valorItem.numero ? `Momento ${valorItem.numero}` : valorItem.momento ? `Evidencia del momento ${valorItem.momento}` : valorItem.pf || `${etiquetaDe(clave)} ${items.length + 1}`);
        const caja = h("div", { clase: "editor-grupo" }, h("div", { clase: "titulo-grupo" }, h("span", {}, String(titulo).slice(0, 90)), quitar), e.el);
        registro.leer = e.leer;
        lista.append(caja);
      } else {
        const control = deNumeros
          ? registrar(h("input", { type: "number", value: valorItem ?? 0 }), oficial)
          : registrar(h("textarea", { rows: 1 }), oficial);
        if (!deNumeros) { control.value = valorItem ?? ""; autoAltura(control); }
        const quitar = registrar(h("button", { type: "button", clase: "boton texto chico", title: "Quitar", onclick: () => { lista.removeChild(fila); items.splice(items.indexOf(registro), 1); opciones.alCambiar && opciones.alCambiar(); } }, "×"), oficial);
        const fila = h("div", { clase: "editor-lista-item" }, control, quitar);
        registro.leer = () => (deNumeros ? Number(control.value || 0) : control.value);
        lista.append(fila);
        if (!alFinal) control.focus();
      }
      items.push(registro);
    }

    v.forEach((x) => agregar(x));
    const anadir = registrar(h("button", { type: "button", clase: "boton secundario chico", onclick: () => {
      let nuevo;
      if (deObjetos) nuevo = v.length ? vacioComo(v[0]) : vacioDeEsquema(esquemaItem, defs);
      else nuevo = deNumeros ? 0 : "";
      agregar(nuevo, false);
      opciones.alCambiar && opciones.alCambiar();
    } }, "+ Añadir"), oficial);
    cont.append(lista, h("div", { clase: "fila" }, anadir));
    void bloqueadoLista;
    return {
      el: cont,
      leer: () => items.map((r) => r.leer()).filter((x) => deObjetos || deNumeros || String(x).trim() !== ""),
    };
  }

  const raiz = nodo(valor, [], opciones.esquema);
  return {
    el: raiz.el,
    leer: raiz.leer,
    desbloquear(si = true) {
      desbloqueado = si;
      for (const [el, oficial] of controles) el.disabled = opciones.soloLectura || (oficial && !desbloqueado);
    },
  };
}

/* Vista de solo lectura, compacta, de un contenido (para secciones ya aprobadas). */
function vistaContenido(valor, nivel = 0) {
  if (valor === null || valor === undefined || valor === "") return h("span", { clase: "suave" }, "—");
  if (Array.isArray(valor)) {
    if (!valor.length) return h("span", { clase: "suave" }, "—");
    if (typeof valor[0] !== "object") return h("ul", {}, valor.map((x) => h("li", {}, String(x))));
    return h("div", {}, valor.map((x) => h("div", { clase: "editor-grupo" }, vistaContenido(x, nivel + 1))));
  }
  if (typeof valor === "object") {
    return h("div", {}, Object.entries(valor).map(([k, v]) =>
      h("div", { clase: "editor-campo" }, h("div", { clase: "etiqueta" }, etiquetaDe(k)), vistaContenido(v, nivel + 1))));
  }
  return h("div", { estilo: "white-space: pre-wrap" }, String(valor));
}
