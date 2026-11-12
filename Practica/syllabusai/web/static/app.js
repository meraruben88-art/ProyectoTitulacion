/* SyllabusAI — página web.

   Estructura: cabecera con la navegación; a la izquierda, fijo, el panel de mallas del CES y
   debajo las noticias (que se actualizan solas) con la caja para preguntarle al agente; a la
   derecha la vista activa. Las vistas se eligen por el fragmento de la URL (#/inicio, #/nuevo,
   #/silabo/7/agente, #/malla/2, #/admin/docentes…). */

"use strict";

const estado = {
  usuario: null, sistema: null, mallas: [], noticias: [], ultimaNoticia: 0, vistas: new Set(),
  formato: null, temporizador: null,
};
const esAdmin = () => estado.usuario && estado.usuario.rol === "admin_corpus";
const raiz = () => document.getElementById("app");

// --- comunicación con el servidor ------------------------------------------------------------

class ErrorApi extends Error {
  constructor(estadoHttp, mensaje) { super(mensaje); this.estadoHttp = estadoHttp; }
}

async function api(metodo, ruta, cuerpo, { formulario = false, crudo = false } = {}) {
  const opciones = { method: metodo, credentials: "same-origin", headers: { "X-SyllabusAI-Web": "1" } };
  if (cuerpo !== undefined) {
    if (formulario) opciones.body = cuerpo;
    else { opciones.body = JSON.stringify(cuerpo); opciones.headers["Content-Type"] = "application/json"; }
  }
  let r;
  try { r = await fetch(ruta, opciones); }
  catch (_) {
    // fetch solo falla así cuando no hay servidor que responda (ventana cerrada o apagado).
    throw new ErrorApi(0, "No hay conexión con el servidor de SyllabusAI. Ábralo con «Iniciar SyllabusAI» (o verifique que su ventana siga abierta) y vuelva a intentar.");
  }
  if (r.status === 401 && ruta !== "/web/login" && ruta !== "/web/yo") {
    estado.usuario = null;
    pantallaAcceso("Su sesión terminó. Vuelva a ingresar.");
    throw new ErrorApi(401, "Sesión vencida");
  }
  if (!r.ok) {
    let detalle = r.statusText;
    try { const j = await r.json(); detalle = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) { /* sin cuerpo */ }
    throw new ErrorApi(r.status, detalle);
  }
  if (crudo) return r;
  const tipo = r.headers.get("content-type") || "";
  return tipo.includes("application/json") ? r.json() : r;
}

function avisar(texto, tipo = "") {
  const el = h("div", { clase: `aviso-emergente ${tipo}` }, texto);
  document.getElementById("avisos").append(el);
  setTimeout(() => el.remove(), tipo === "error" ? 7000 : 4000);
}

async function conCarga(boton, accion, textoCarga = "Trabajando…") {
  const original = boton ? boton.innerHTML : null;
  if (boton) { boton.disabled = true; boton.innerHTML = ""; boton.append(h("span", { clase: "girando" }), " ", textoCarga); }
  try { return await accion(); }
  catch (e) { if (e.estadoHttp !== 401) avisar(e.message || String(e), "error"); return undefined; }
  finally { if (boton) { boton.disabled = false; boton.innerHTML = original; } }
}

async function descargar(ruta, metodo = "POST") {
  const r = await api(metodo, ruta, undefined, { crudo: true });
  const blob = await r.blob();
  const disp = r.headers.get("content-disposition") || "";
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disp);
  const nombre = m ? decodeURIComponent(m[1]) : "archivo";
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: nombre });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return nombre;
}

function modal(titulo, contenido, { ancho = false } = {}) {
  const velo = h("div", { clase: "velo", onclick: (e) => { if (e.target === velo) cerrar(); } });
  const cerrar = () => velo.remove();
  velo.append(h("div", { clase: `modal ${ancho ? "ancho" : ""}`, role: "dialog", "aria-modal": "true" },
    h("div", { clase: "fila entre" }, h("h2", {}, titulo), h("button", { clase: "boton texto", onclick: cerrar }, "Cerrar")),
    contenido));
  document.body.append(velo);
  return cerrar;
}

const fechaCorta = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const seg = (Date.now() - d.getTime()) / 1000;
  if (seg < 60) return "ahora";
  if (seg < 3600) return `hace ${Math.floor(seg / 60)} min`;
  if (seg < 86400) return `hace ${Math.floor(seg / 3600)} h`;
  return d.toLocaleDateString("es-EC", { day: "2-digit", month: "short", year: "numeric" });
};

const ESTADOS_SILABO = { borrador: ["Borrador", ""], en_revision: ["En revisión", "morado"], aprobado: ["Aprobado", "verde"], exportado: ["Exportado", "azul"] };
const ESTADOS_SECCION = { pendiente: ["Pendiente", ""], propuesta: ["Propuesta", "morado"], aprobada: ["Aprobada", "verde"], abstenida: ["Abstención", "ambar"] };
const CATEGORIAS = { silabo: ["Formato del sílabo", "morado"], normativa: ["Normativa", "azul"], malla: ["Malla", "verde"], documento: ["Documento", ""], externa: ["Otras fuentes", "naranja"], aviso: ["Aviso", "rojo"] };
const pastilla = (texto, color = "") => h("span", { clase: `pastilla ${color}` }, texto);
const ROLES = { docente: "Docente", admin_corpus: "Administrador", evaluador: "Evaluador" };
const TIPOS_DOC = { normativa: "Normativa", perfil_egreso: "Perfil de egreso", malla: "Malla", contenidos_minimos: "Contenidos mínimos", silabo_aprobado: "Sílabo aprobado", plantilla: "Plantilla / formato" };

// --- acceso ----------------------------------------------------------------------------------

function pantallaAcceso(mensaje) {
  clearInterval(estado.temporizador);
  const correo = h("input", { type: "email", autocomplete: "username", required: true, placeholder: "nombre@uti.edu.ec" });
  const clave = h("input", { type: "password", autocomplete: "current-password", required: true });
  const error = h("div", { clase: "alerta bloqueante", hidden: !mensaje }, mensaje || "");
  const boton = h("button", { clase: "boton", type: "submit", estilo: "width:100%;justify-content:center;padding:11px" }, "Entrar");
  const form = h("form", { onsubmit: async (e) => {
    e.preventDefault();
    error.hidden = true;
    await conCarga(boton, async () => {
      try {
        estado.usuario = await api("POST", "/web/login", { correo: correo.value, clave: clave.value });
        await arrancar();
      } catch (err) { error.textContent = err.message; error.hidden = false; }
    }, "Entrando…");
  } },
    h("img", { src: "/static/logo-color.png", alt: "Universidad Indoamérica" }),
    h("h2", {}, "Ingresar"),
    h("p", { clase: "media" }, "Use la cuenta que le entregó el administrador."),
    error,
    h("label", { clase: "campo" }, h("span", {}, "Correo institucional"), correo),
    h("label", { clase: "campo" }, h("span", {}, "Contraseña"), clave),
    boton);
  raiz().replaceChildren(h("div", { clase: "acceso" },
    h("div", { clase: "acceso-marca" },
      h("img", { src: "/static/logo-blanco.png", alt: "Universidad Indoamérica" }),
      h("div", {},
        h("div", { clase: "franja" }),
        h("h1", {}, "SyllabusAI: el sílabo con un agente que cita sus fuentes"),
        h("p", {}, "Mallas del CES, normativa vigente y Guía de PIS en un solo lugar. El agente propone cada sección con evidencia; usted revisa, corrige, aprueba y exporta."),
      ),
      h("small", { estilo: "color:#ffffff99" }, "Universidad Tecnológica Indoamérica · Facultad de Ingenierías")),
    h("div", { clase: "acceso-formulario" }, h("div", { clase: "tarjeta" }, form))));
  correo.focus();
}

// --- arranque y estructura -------------------------------------------------------------------

async function arrancar() {
  try { estado.usuario = estado.usuario || await api("GET", "/web/yo"); }
  catch (_) { pantallaAcceso(); return; }
  [estado.sistema, estado.mallas, estado.formato] = await Promise.all([
    api("GET", "/web/estado"), api("GET", "/web/mallas"), api("GET", "/formato"),
  ]);
  estructura();
  await cargarNoticias(true);
  clearInterval(estado.temporizador);
  estado.temporizador = setInterval(() => cargarNoticias(false), 30000);
  window.onhashchange = rutear;
  rutear();
}

function estructura() {
  const u = estado.usuario;
  const s = estado.sistema;
  const nav = [["#/inicio", "Inicio"], ["#/nuevo", "Nuevo sílabo"]];
  if (esAdmin()) nav.push(["#/admin/docentes", "Docentes"], ["#/admin/documentos", "Documentos"], ["#/admin/mallas", "Mallas"], ["#/admin/noticias", "Noticias"], ["#/admin/sistema", "Sistema"]);
  const menu = h("div", { clase: "desplegable", hidden: true },
    h("div", { clase: "quien" }, h("b", {}, u.nombre), h("br"), h("small", {}, `${u.correo} · ${ROLES[u.rol] || u.rol}`)),
    h("button", { onclick: () => { menu.hidden = true; cambiarClave(); } }, "Cambiar contraseña"),
    h("button", { onclick: async () => { await api("POST", "/web/logout"); estado.usuario = null; pantallaAcceso(); } }, "Cerrar sesión"));
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-usuario")) menu.hidden = true; });
  raiz().replaceChildren(
    h("header", { clase: "cabecera" },
      h("a", { clase: "marca", href: "#/inicio" }, h("img", { src: "/static/logo-blanco.png", alt: "Universidad Indoamérica" }), h("span", {}, "SyllabusAI")),
      h("nav", { clase: "navegacion", id: "nav" }, nav.map(([href, t]) => h("a", { href }, t))),
      h("div", { clase: "derecha" },
        h("span", { clase: "chip-modelo", title: s.llm.url || "Modelo determinista para probar sin GPU" }, "Modelo: ", h("b", {}, s.llm.modelo), ` · ${s.llm.destino}`),
        h("div", { clase: "menu-usuario" }, h("button", { onclick: () => { menu.hidden = !menu.hidden; } }, u.nombre.split(" ")[0], " ▾"), menu))),
    h("div", { clase: "cuerpo" },
      h("aside", { clase: "lateral" },
        h("section", { clase: "panel-mallas", "aria-label": "Mallas del CES", id: "panel-mallas" }),
        h("section", { clase: "panel-noticias", "aria-label": "Noticias", id: "panel-noticias" }),
        panelPregunta()),
      h("main", { clase: "principal", id: "principal" })));
  pintarMallas();
}

function marcarNavegacion() {
  const actual = location.hash.split("/").slice(0, 3).join("/");
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("activo", actual.startsWith(a.getAttribute("href"))));
  document.querySelectorAll(".malla-item").forEach((a) => a.classList.toggle("activo", location.hash === a.getAttribute("href")));
}

function principal(...hijos) {
  const p = document.getElementById("principal");
  p.replaceChildren(...hijos);
  window.scrollTo(0, 0);
  return p;
}

async function rutear() {
  if (!estado.usuario) return;
  const partes = (location.hash || "#/inicio").slice(2).split("/");
  marcarNavegacion();
  try {
    if (partes[0] === "nuevo") return await vistaNuevo(partes[1]);
    if (partes[0] === "silabo") return await vistaSilabo(Number(partes[1]), partes[2] || "agente");
    if (partes[0] === "malla") return await vistaMalla(Number(partes[1]));
    if (partes[0] === "admin" && esAdmin()) {
      const vistas = { docentes: vistaDocentes, documentos: vistaDocumentos, mallas: vistaAdminMallas, noticias: vistaAdminNoticias, sistema: vistaSistema };
      return await (vistas[partes[1]] || vistaDocentes)();
    }
    return await vistaInicio();
  } catch (e) {
    if (e.estadoHttp !== 401) principal(h("div", { clase: "alerta bloqueante" }, e.message || String(e)));
  }
}

function cambiarClave() {
  const actual = h("input", { type: "password", autocomplete: "current-password" });
  const nueva = h("input", { type: "password", autocomplete: "new-password", minlength: 8 });
  const boton = h("button", { clase: "boton" }, "Guardar");
  const cerrar = modal("Cambiar contraseña", h("div", {},
    h("label", { clase: "campo" }, h("span", {}, "Contraseña actual"), actual),
    h("label", { clase: "campo" }, h("span", {}, "Contraseña nueva (mínimo 8 caracteres)"), nueva),
    h("div", { clase: "fila fin" }, boton)));
  boton.onclick = () => conCarga(boton, async () => {
    await api("POST", "/web/clave", { actual: actual.value, nueva: nueva.value });
    avisar("Contraseña actualizada", "exito");
    cerrar();
  });
}

// --- panel de mallas (fijo, arriba a la izquierda) ---------------------------------------------

function pintarMallas() {
  const panel = document.getElementById("panel-mallas");
  const lista = estado.mallas.length
    ? estado.mallas.map((m) => h("a", { clase: "malla-item", href: `#/malla/${m.id}` },
      h("span", { clase: "malla-sigla" }, m.carrera),
      h("span", {}, h("span", { clase: "nombre" }, m.nombre),
        h("small", {}, `${m.asignaturas} asignaturas · ${m.estado === "publicada" ? "publicada" : `${m.revisadas} revisadas`}`))))
    : [h("p", { clase: "suave", estilo: "font-size:13px" }, esAdmin()
      ? h("span", {}, "Aún no hay mallas. ", h("a", { href: "#/admin/mallas" }, "Importe la carpeta MALLAS"), ".")
      : "El administrador todavía no ha cargado las mallas.")];
  panel.replaceChildren(h("div", { clase: "panel-titulo" }, h("h3", {}, "Mallas curriculares (CES)"),
    esAdmin() ? h("a", { href: "#/admin/mallas", clase: "boton texto chico" }, "Gestionar") : null), ...lista);
  marcarNavegacion();
}

// --- noticias ------------------------------------------------------------------------------

async function cargarNoticias(inicial) {
  let nuevas;
  try { nuevas = await api("GET", `/web/noticias${inicial ? "" : `?despues_de=${estado.ultimaNoticia}`}`); }
  catch (_) { return; }
  if (!inicial && nuevas.length) avisar(`${nuevas.length} noticia(s) nueva(s): ${nuevas[0].titulo}`);
  const ids = new Set(estado.noticias.map((n) => n.id));
  estado.noticias = [...nuevas.filter((n) => !ids.has(n.id)), ...estado.noticias].slice(0, 60);
  if (!inicial) nuevas.forEach((n) => estado.vistas.add(n.id));
  estado.ultimaNoticia = Math.max(estado.ultimaNoticia, ...estado.noticias.map((n) => n.id), 0);
  pintarNoticias();
}

function pintarNoticias() {
  const panel = document.getElementById("panel-noticias");
  if (!panel) return;
  const tarjetas = estado.noticias.map((n) => {
    const [cat, color] = CATEGORIAS[n.categoria] || [n.categoria, ""];
    const tarjeta = h("article", { clase: `noticia ${n.importante ? "importante" : ""} ${estado.vistas.has(n.id) ? "nueva" : ""}`,
      onclick: () => { tarjeta.classList.toggle("abierta"); detalle.hidden = !detalle.hidden; tarjeta.classList.remove("nueva"); estado.vistas.delete(n.id); } },
      h("div", { clase: "noticia-meta" }, pastilla(cat, color), h("span", {}, fechaCorta(n.fecha))),
      h("h4", {}, n.titulo),
      h("div", { clase: "resumen" }, n.resumen));
    const detalle = h("div", { hidden: true },
      n.puntos.length ? h("ul", {}, n.puntos.map((p) => h("li", {}, p))) : null,
      n.citas.length ? h("div", { clase: "citas" }, "Fuentes: ", n.citas.join(" · ")) : null,
      n.fuente_url ? h("div", { clase: "citas" }, h("a", { href: n.fuente_url, target: "_blank", rel: "noopener" }, "Ver la publicación original")) : null,
      n.carrera !== "TODAS" ? h("div", { clase: "citas" }, `Carrera: ${n.carrera}`) : null);
    tarjeta.append(detalle);
    return tarjeta;
  });
  panel.replaceChildren(
    h("div", { clase: "panel-titulo" }, h("h3", {}, "Noticias y cambios"), h("small", {}, "se actualiza sola")),
    ...(tarjetas.length ? tarjetas : [h("p", { clase: "suave", estilo: "font-size:13px" }, "Sin novedades por ahora. Cuando cambie el formato del sílabo, una normativa o una malla, aparecerá aquí con el resumen del agente.")]));
}

function panelPregunta() {
  const area = h("textarea", { rows: 2, placeholder: "Pregúntele al agente sobre normativa, formato o novedades…" });
  const salida = h("div", { clase: "respuesta-agente" });
  const boton = h("button", { clase: "boton chico" }, "Preguntar");
  boton.onclick = () => conCarga(boton, async () => {
    if (!area.value.trim()) return;
    const r = await api("POST", "/web/noticias/preguntar", { pregunta: area.value });
    salida.replaceChildren(
      r.abstencion ? h("div", { clase: "alerta advertencia" }, r.abstencion) : h("p", {}, r.respuesta),
      r.puntos && r.puntos.length ? h("ul", {}, r.puntos.map((p) => h("li", {}, p))) : null,
      ...(r.citas || []).map((c) => h("div", { clase: "cita" }, h("details", {}, h("summary", {}, `${c.documento} · v${c.version} · p. ${c.pagina}`), h("p", {}, c.texto)))));
  }, "Buscando…");
  return h("section", { clase: "pregunta-agente" }, area, h("div", { clase: "fila fin", estilo: "margin-top:6px" }, boton), salida);
}

// --- inicio --------------------------------------------------------------------------------

async function vistaInicio() {
  const silabos = await api("GET", "/silabos");
  const contar = (e) => silabos.filter((s) => s.estado === e).length;
  const filas = silabos.map((s) => {
    const [et, color] = ESTADOS_SILABO[s.estado] || [s.estado, ""];
    return h("tr", {},
      h("td", {}, h("a", { href: `#/silabo/${s.id}/agente` }, h("b", {}, s.asignatura)), h("br"), h("small", {}, `Periodo ${s.periodo} · actualizado ${fechaCorta(s.actualizado)}`)),
      h("td", {}, pastilla(et, color)),
      h("td", {}, h("div", { clase: "progreso", title: `${s.aprobadas} de ${s.secciones}` }, h("i", { estilo: `width:${(100 * s.aprobadas) / Math.max(1, s.secciones)}%` })), h("small", {}, `${s.aprobadas}/${s.secciones} secciones`)),
      h("td", { estilo: "text-align:right" },
        h("a", { clase: "boton secundario chico", href: `#/silabo/${s.id}/agente` }, "Agente"), " ",
        h("a", { clase: "boton secundario chico", href: `#/silabo/${s.id}/pis` }, "PIS"), " ",
        h("a", { clase: "boton chico", href: `#/silabo/${s.id}/documento` }, "Documento")));
  });
  principal(
    h("div", { clase: "encabezado-vista" },
      h("div", {}, h("h1", {}, `Hola, ${estado.usuario.nombre.split(" ")[0]}`),
        h("p", {}, esAdmin() ? "Administración de SyllabusAI: cuentas, corpus, mallas y noticias." : "Elabore su sílabo con el agente: usted decide, el agente propone y cita.")),
      h("a", { clase: "boton naranja", href: "#/nuevo" }, "+ Nuevo sílabo")),
    h("div", { clase: "estadisticas" },
      [["Sílabos", silabos.length], ["En revisión", contar("en_revision")], ["Aprobados", contar("aprobado")], ["Exportados", contar("exportado")]]
        .map(([t, n]) => h("div", { clase: "estadistica" }, h("b", {}, n), h("span", {}, t)))),
    h("div", { clase: "tarjeta" },
      h("h2", {}, esAdmin() ? "Todos los sílabos" : "Mis sílabos"),
      silabos.length
        ? h("div", { clase: "envoltura-tabla" }, h("table", { clase: "tabla" },
          h("thead", {}, h("tr", {}, h("th", {}, "Proyecto Formativo"), h("th", {}, "Estado"), h("th", {}, "Avance"), h("th", {}, ""))),
          h("tbody", {}, filas)))
        : h("div", { clase: "vacio" }, h("p", {}, "Todavía no tiene sílabos."), h("a", { clase: "boton", href: "#/nuevo" }, "Crear el primero"))),
    h("div", { clase: "tarjeta plana" },
      h("h3", {}, "¿Cómo funciona?"),
      h("ol", { clase: "media" },
        h("li", {}, "Elija la asignatura de la malla del CES: sus resultados de aprendizaje, contenidos mínimos y horas se importan sin cambios."),
        h("li", {}, "Cuente al agente cómo quiere su sílabo (problema, producto, metodología, IA, evaluación)."),
        h("li", {}, "Revise cada sección: apruébela, corríjala o pídale cambios en lenguaje natural. Cada propuesta cita sus fuentes."),
        h("li", {}, "Arme el PIS con el agente y ajústelo a su conveniencia."),
        h("li", {}, "Corrija el documento final completo y expórtelo en Word o PDF."))));
}

// --- nuevo sílabo (formulario con el agente) ------------------------------------------------

async function vistaNuevo(asignaturaInicial) {
  const asignaturas = await api("GET", "/asignaturas");
  const f = estado.formato;
  if (!asignaturas.length) {
    principal(h("div", { clase: "tarjeta vacio" }, h("p", {}, "No hay asignaturas en el catálogo. El administrador debe importar las mallas del CES.")));
    return;
  }
  const carreras = [...new Set(asignaturas.map((a) => a.carrera))];
  const nombreCarrera = (c) => (estado.mallas.find((m) => m.carrera === c) || {}).nombre || c;
  const inicial = asignaturas.find((a) => String(a.id) === String(asignaturaInicial));
  const selCarrera = h("select", {}, carreras.map((c) => h("option", { value: c }, `${nombreCarrera(c)} (${c})`)));
  const selAsignatura = h("select", {});
  const ficha = h("div", {});
  // Por defecto, la carrera del docente (o ITI); si llega desde una malla, la de esa asignatura.
  const preferida = [estado.usuario.carrera, "ITI"].find((c) => c && carreras.includes(c));
  if (inicial) selCarrera.value = inicial.carrera;
  else if (preferida) selCarrera.value = preferida;

  function llenarAsignaturas() {
    const lista = asignaturas.filter((a) => a.carrera === selCarrera.value);
    const niveles = [...new Set(lista.map((a) => a.nivel))].sort((a, b) => a - b);
    selAsignatura.replaceChildren(...niveles.map((n) => h("optgroup", { label: `Nivel ${n}` },
      lista.filter((a) => a.nivel === n).map((a) => h("option", { value: a.id }, `${a.codigo} · ${a.nombre}${a.origen === "ejemplo" ? " (ejemplo)" : ""}${!a.ficha_valida ? " — ficha incompleta" : ""}`)))));
    if (inicial && inicial.carrera === selCarrera.value) selAsignatura.value = inicial.id;
    mostrarFicha();
  }
  function mostrarFicha() {
    const a = asignaturas.find((x) => String(x.id) === selAsignatura.value);
    if (!a) { ficha.replaceChildren(); return; }
    const fi = a.ficha || {};
    ficha.replaceChildren(h("div", { clase: "tarjeta plana", estilo: "background:var(--papel-hundido)" },
      h("div", { clase: "fila entre" }, h("h3", {}, `🔒 Datos oficiales que se importan sin modificación`),
        a.origen === "malla_ces" ? pastilla(a.revisada ? "Ficha revisada" : "Extraída del CES · pendiente de revisión", a.revisada ? "verde" : "ambar") : pastilla("Catálogo de ejemplo")),
      !a.ficha_valida ? h("div", { clase: "alerta bloqueante" }, `La ficha está incompleta y no se puede usar todavía: ${a.error_ficha}. El administrador debe completarla en Mallas.`) : null,
      h("p", { clase: "media" }, `Horas: contacto ${fi.horas_contacto ?? "—"} · práctico-experimentales ${fi.horas_practicas ?? "—"} · autónomas ${fi.horas_autonomas ?? "—"} · total ${a.horas}`),
      h("b", {}, "Resultados de aprendizaje"),
      h("ol", {}, (fi.resultados_aprendizaje || []).map((r) => h("li", {}, r.enunciado))),
      h("b", {}, "Contenidos mínimos"),
      h("ul", {}, (fi.contenidos_minimos || []).map((c) => h("li", {}, c)))));
    boton.disabled = !a.ficha_valida;
  }
  selCarrera.onchange = llenarAsignaturas;
  selAsignatura.onchange = mostrarFicha;

  const campoTexto = (etiqueta, valor = "", ayuda = "", atributos = {}) => {
    const input = h("input", { type: "text", value: valor, ...atributos });
    return [h("label", { clase: "campo" }, h("span", {}, etiqueta), input, ayuda ? h("div", { clase: "ayuda" }, ayuda) : null), input];
  };
  const campoArea = (etiqueta, ayuda = "", placeholder = "", filas = 3) => {
    const area = h("textarea", { rows: filas, placeholder });
    return [h("label", { clase: "campo" }, h("span", {}, etiqueta), area, ayuda ? h("div", { clase: "ayuda" }, ayuda) : null), area];
  };
  const multiple = (etiqueta, opciones) => {
    const caja = h("div", { clase: "fila", estilo: "gap:6px" });
    const marcados = new Set();
    opciones.forEach((o) => {
      const chip = h("button", { type: "button", clase: "pastilla", estilo: "cursor:pointer;border:1px solid var(--linea-fuerte)", onclick: () => {
        if (marcados.has(o)) { marcados.delete(o); chip.className = "pastilla"; } else { marcados.add(o); chip.className = "pastilla morado"; }
      } }, o);
      caja.append(chip);
    });
    return [h("div", { clase: "campo" }, h("span", { estilo: "display:block;font-weight:600;font-size:13px;color:var(--tinta-media);margin-bottom:6px" }, etiqueta), caja), () => [...marcados]];
  };
  const seleccion = (etiqueta, opciones) => {
    const sel = h("select", {}, h("option", { value: "" }, "(sin preferencia)"), opciones.map((o) => h("option", { value: o }, o)));
    return [h("label", { clase: "campo" }, h("span", {}, etiqueta), sel), sel];
  };

  const [cPeriodo, iPeriodo] = campoTexto("Periodo académico", "B26");
  const iSemanas = h("input", { type: "number", value: 16, min: 8, max: 24 });
  const [cProblema, iProblema] = campoArea("Problema o necesidad del territorio (con datos)",
    "Necesidad documentada + respuesta insuficiente + actores. El agente no inventa datos: sin esta descripción la sección 7.3 se abstiene.", "", 4);
  const [cFuentes, iFuentes] = campoArea("Fuentes que documentan el problema", "", "", 2);
  const [cEscenario, iEscenario] = campoTexto("Escenario", "la Universidad Tecnológica Indoamérica, sede Quito");
  const [cActores, iActores] = campoTexto("Actores del contexto", "estudiantes, docentes y la comunidad vinculada");
  const [cProducto, iProducto] = campoTexto("¿Qué construirán los estudiantes? (producto integrador)", "", "", { placeholder: "p. ej. un asistente conversacional que oriente a los estudiantes nuevos" });
  const [cTema, iTema] = campoTexto("Tema del reto", "", "", { placeholder: "p. ej. la deserción estudiantil en primer nivel" });
  const [cMetodologia, leerMetodologia] = multiple("Metodología", f.metodologias);
  const [cTecnologias, leerTecnologias] = multiple("Tecnologías / software", f.tecnologias);
  const [cHabilidades, leerHabilidades] = multiple("Habilidades blandas que se ejercitan y evalúan", f.habilidades_blandas);
  const [cTipos, leerTipos] = multiple("Tipos de evaluación", ["heteroevaluacion", "coevaluacion", "autoevaluacion"]);
  const [cTrabajo, iTrabajo] = seleccion("Modalidad de trabajo", ["individual", "parejas", "equipos de 3", "equipos de 4", "equipos de 5"]);
  const [cIA, iIA] = seleccion("Uso de IA por los estudiantes", ["permitida", "limitada", "prohibida"]);
  const [cInstrumento, iInstrumento] = seleccion("Instrumento de evaluación", f.instrumentos);
  const [cBiblio, iBiblio] = campoArea("Bibliografía que usted propone (una referencia por línea)", "El agente solo cita referencias de la malla, del corpus o las que usted escriba aquí.", "", 3);
  const [cIndicaciones, iIndicaciones] = campoArea("Otras indicaciones para el agente (texto libre)", "",
    "p. ej. «Que trabajen en equipos de 3, momento 3 con 30 %, énfasis en la ética de los datos.»", 3);

  const boton = h("button", { clase: "boton naranja", type: "submit" }, "Crear sílabo e iniciar el agente");
  const form = h("form", { onsubmit: (e) => {
    e.preventDefault();
    conCarga(boton, async () => {
      const preferencias = {
        producto: iProducto.value.trim() || null, tema: iTema.value.trim() || null,
        metodologia: leerMetodologia(), trabajo: iTrabajo.value || null, tecnologias: leerTecnologias(),
        politica_ia: iIA.value || null, tipos_evaluacion: leerTipos(), instrumento: iInstrumento.value || null,
        habilidades_blandas: leerHabilidades(),
        bibliografia: iBiblio.value.split("\n").map((x) => x.trim()).filter(Boolean),
      };
      const datos = {
        semanas_periodo: Number(iSemanas.value || 16), contexto_problema: iProblema.value, fuentes_problema: iFuentes.value,
        escenario: iEscenario.value, actores: iActores.value, preferencias, indicaciones_generales: iIndicaciones.value,
        docente: estado.usuario.nombre, correo_docente: estado.usuario.correo,
      };
      const s = await api("POST", "/silabos", { asignatura_id: Number(selAsignatura.value), periodo: iPeriodo.value.trim() || "B26", datos_generales: datos });
      avisar("Sílabo creado: el agente empezó por la información general.", "exito");
      location.hash = `#/silabo/${s.id}/agente`;
    }, "El agente está trabajando…");
  } },
    h("div", { clase: "tarjeta" },
      h("h2", {}, "1. Proyecto Formativo"),
      h("div", { clase: "rejilla dos" }, h("label", { clase: "campo" }, h("span", {}, "Carrera"), selCarrera), h("label", { clase: "campo" }, h("span", {}, "Asignatura"), selAsignatura)),
      ficha),
    h("div", { clase: "tarjeta" },
      h("h2", {}, "2. Periodo y problema del territorio"),
      h("div", { clase: "rejilla dos" }, cPeriodo, h("label", { clase: "campo" }, h("span", {}, "Semanas del periodo"), iSemanas)),
      cProblema, cFuentes, h("div", { clase: "rejilla dos" }, cEscenario, cActores)),
    h("div", { clase: "tarjeta" },
      h("h2", {}, "3. ¿Cómo quiere su sílabo?"),
      h("p", { clase: "media" }, "Todo es opcional. El agente lo recuerda en todas las secciones y usted puede cambiarlo después conversando con él."),
      h("div", { clase: "rejilla dos" }, cProducto, cTema), cMetodologia, cTecnologias,
      h("div", { clase: "rejilla tres" }, cTrabajo, cIA, cInstrumento), cTipos, cHabilidades, cBiblio),
    h("div", { clase: "tarjeta" }, h("h2", {}, "4. Indicaciones para el agente"), cIndicaciones,
      h("div", { clase: "fila fin" }, boton)));
  llenarAsignaturas();
  principal(h("div", { clase: "encabezado-vista" }, h("div", {}, h("div", { clase: "migas" }, h("a", { href: "#/inicio" }, "Inicio"), " / Nuevo sílabo"),
    h("h1", {}, "Nuevo sílabo con el agente"), h("p", {}, "Formato institucional: " + estado.sistema.formato))), form);
}

// --- espacio de trabajo de un sílabo -----------------------------------------------------------

async function vistaSilabo(id, pestana) {
  const s = await api("GET", `/silabos/${id}`);
  const [et, color] = ESTADOS_SILABO[s.estado] || [s.estado, ""];
  const pestanas = [["agente", "Agente por secciones"], ["pis", "PIS"], ["documento", "Documento final editable"], ["exportar", "Exportar"]];
  const cuerpo = h("div", {});
  principal(
    h("div", { clase: "encabezado-vista" },
      h("div", {}, h("div", { clase: "migas" }, h("a", { href: "#/inicio" }, "Inicio"), ` / Sílabo ${s.id}`),
        h("h1", {}, `${s.asignatura.codigo} · ${s.asignatura.nombre}`),
        h("p", {}, `Periodo ${s.periodo} · `, pastilla(et, color))),
      h("div", { clase: "fila" }, h("span", { clase: "pastilla morado" }, `${s.secciones.filter((x) => x.estado === "aprobada").length}/${s.secciones.length} secciones aprobadas`))),
    h("nav", { clase: "pestanas" }, pestanas.map(([k, t]) => h("a", { href: `#/silabo/${id}/${k}`, clase: k === pestana ? "activo" : "" }, t))),
    cuerpo);
  const vistas = { agente: pestanaAgente, pis: pestanaPIS, documento: pestanaDocumento, exportar: pestanaExportar };
  await (vistas[pestana] || pestanaAgente)(s, cuerpo);
}

function listaCitas(citas) {
  if (!citas || !citas.length) return h("p", { clase: "suave", estilo: "font-size:13px" }, "Sin fuentes: datos importados de la ficha curricular o escritos por usted.");
  return h("div", {}, citas.map((c) => h("div", { clase: "cita" }, h("details", {},
    h("summary", {}, `${c.documento} · v${c.version} · p. ${c.pagina} `, c.vigente === false ? pastilla("obsoleto", "rojo") : null),
    h("p", {}, c.texto)))));
}

function listaHallazgos(hallazgos, silaboId, alCambiar) {
  const abiertos = hallazgos.filter((x) => !x.resuelto);
  if (!abiertos.length) return h("div", { clase: "alerta exito" }, "Sin observaciones.");
  return h("div", {}, abiertos.map((x) => {
    const caja = h("div", { clase: `alerta ${x.severidad}` }, h("b", {}, x.regla), " · ", x.mensaje);
    if (x.severidad === "advertencia" && silaboId) {
      const boton = h("button", { clase: "boton texto chico", onclick: async () => {
        const just = prompt("Justificación para descartar esta advertencia:");
        if (!just) return;
        await conCarga(boton, () => api("POST", `/silabos/${silaboId}/hallazgos/${x.id}/descartar`, { justificacion: just }));
        alCambiar && alCambiar();
      } }, "Descartar con justificación");
      caja.append(h("div", {}, boton));
    }
    return caja;
  }));
}

async function pestanaAgente(s, cuerpo) {
  const pausa = s.pausa;
  const actual = pausa.clave;
  let vista = actual || (s.secciones.find((x) => x.estado !== "aprobada") || s.secciones[0]).clave;
  const recargar = () => vistaSilabo(s.id, "agente");

  const pasos = h("div", { clase: "pasos" });
  const centro = h("div", {});
  const derecha = h("div", { clase: "columna-derecha" });

  function pintarPasos() {
    pasos.replaceChildren(...s.secciones.map((x) => h("div", { clase: `paso ${x.estado} ${x.clave === vista ? "actual" : ""}`, onclick: () => { vista = x.clave; pintar(); } },
      h("span", { clase: "marca-estado" }, x.estado === "aprobada" ? "✓" : x.estado === "abstenida" ? "!" : x.clave === actual ? "●" : ""),
      h("span", {}, x.titulo))));
  }

  function pintar() {
    pintarPasos();
    const sec = s.secciones.find((x) => x.clave === vista);
    const enRevision = pausa.tipo === "revision_seccion" && sec.clave === actual;
    const [et, color] = ESTADOS_SECCION[sec.estado] || [sec.estado, ""];
    centro.replaceChildren();
    if (pausa.tipo === "sin_iniciar") {
      const b = h("button", { clase: "boton", onclick: () => conCarga(b, async () => { await api("POST", `/silabos/${s.id}/continuar`); recargar(); }, "Iniciando…") }, "Iniciar el agente");
      centro.append(h("div", { clase: "tarjeta" }, h("p", {}, "El agente todavía no empezó este sílabo."), b));
    }
    if (pausa.tipo === "correccion") {
      centro.append(h("div", { clase: "tarjeta" }, h("h2", {}, "La verificación encontró problemas bloqueantes"),
        ...pausa.hallazgos.map((x) => h("div", { clase: "alerta bloqueante" }, h("b", {}, x.regla), " · ", x.mensaje, x.seccion ? h("div", {},
          h("button", { clase: "boton chico", onclick: (e) => conCarga(e.target, async () => { await api("POST", `/silabos/${s.id}/secciones/${x.seccion}/reabrir`); recargar(); }) }, `Reabrir «${x.seccion}»`)) : null)),
        h("div", { clase: "fila" }, h("button", { clase: "boton secundario", onclick: (e) => conCarga(e.target, async () => { await api("POST", `/silabos/${s.id}/validar`); recargar(); }) }, "Verificar de nuevo"),
          h("a", { clase: "boton", href: `#/silabo/${s.id}/documento` }, "Corregir en el documento final"))));
    }
    if (pausa.tipo === "terminado") {
      centro.append(h("div", { clase: "alerta exito" }, h("b", {}, "El agente terminó todas las secciones. "),
        "Ahora puede corregir el sílabo completo en el ", h("a", { href: `#/silabo/${s.id}/documento` }, "documento final editable"), " y exportarlo."));
    }
    const tarjeta = h("div", { clase: "tarjeta" },
      h("div", { clase: "fila entre" }, h("h2", {}, sec.titulo), h("span", {}, pastilla(et, color), " ", sec.version ? h("small", {}, `versión ${sec.version} · ${sec.origen === "docente" ? "editada por usted" : "propuesta del agente"}`) : null)));
    if (enRevision && pausa.error) tarjeta.append(h("div", { clase: "alerta bloqueante" }, pausa.error));
    if (sec.nota) tarjeta.append(h("div", { clase: "nota-agente" }, h("b", {}, "El agente: "), sec.nota));
    if (!sec.contenido) {
      tarjeta.append(h("p", { clase: "suave" }, "Esta sección todavía no tiene propuesta."));
    } else if (enRevision) {
      const oficiales = { identificacion: ["*"], resultados_aprendizaje: ["codigo", "enunciado"], contenidos: ["contenidos_minimos"],
        planeacion_momentos: ["numero", "semanas", "ra", "horas_contacto", "horas_practicas", "horas_autonomas", "peso"], evaluacion: ["momento", "ra", "peso"] }[sec.clave] || [];
      const editor = crearEditor(sec.contenido, { oficiales });
      tarjeta.append(editor.el);
      const indicacion = h("textarea", { rows: 2, placeholder: "Pídale un cambio al agente: «más énfasis en la práctica», «equipos de 3», «prohíbe la IA en el momento 1»…" });
      const vivo = h("div", { clase: "en-vivo", hidden: true });
      const bAprobar = h("button", { clase: "boton exito" }, "Aprobar y continuar");
      const bGuardar = h("button", { clase: "boton secundario" }, "Guardar mi edición");
      const bRegenerar = h("button", { clase: "boton" }, "Pedir al agente");
      bAprobar.onclick = () => enVivo(bAprobar, { accion: "aprobar", contenido: editor.leer() });
      bRegenerar.onclick = () => { if (!indicacion.value.trim()) { avisar("Escriba qué quiere cambiar", "error"); return; } enVivo(bRegenerar, { accion: "regenerar", indicacion: indicacion.value }); };
      bGuardar.onclick = () => conCarga(bGuardar, async () => { await api("PUT", `/silabos/${s.id}/secciones/${sec.clave}`, { contenido: editor.leer() }); avisar("Edición guardada y validada", "exito"); recargar(); });
      async function enVivo(boton, cuerpoPeticion) {
        vivo.hidden = false;
        const pasosVivo = h("div", { clase: "pasos-vivo" });
        const texto = h("pre", {});
        vivo.replaceChildren(h("b", {}, "El agente está trabajando…"), pasosVivo, texto);
        await conCarga(boton, async () => {
          const r = await api("POST", `/silabos/${s.id}/secciones/${sec.clave}/stream`, cuerpoPeticion, { crudo: true });
          const lector = r.body.getReader();
          const dec = new TextDecoder();
          let resto = "";
          for (;;) {
            const { value, done } = await lector.read();
            if (done) break;
            resto += dec.decode(value, { stream: true });
            const partes = resto.split("\n\n");
            resto = partes.pop();
            for (const p of partes) {
              if (!p.startsWith("data:")) continue;
              const ev = JSON.parse(p.slice(5));
              if (ev.tipo === "paso") pasosVivo.append(h("div", {}, `${ev.clave ? `[${ev.clave}] ` : ""}${ev.texto}`));
              else if (ev.tipo === "token") { texto.textContent += ev.texto; texto.scrollTop = texto.scrollHeight; }
              else if (ev.tipo === "error") throw new Error(ev.mensaje);
              else if (ev.tipo === "fin") { avisar(cuerpoPeticion.accion === "aprobar" ? "Sección aprobada" : "Nueva versión lista", "exito"); }
            }
          }
          recargar();
        }, cuerpoPeticion.accion === "aprobar" ? "Aprobando…" : "Regenerando…");
      }
      tarjeta.append(h("div", { clase: "conversacion" }, h("b", {}, "Conversar con el agente sobre esta sección"), indicacion,
        h("div", { clase: "fila entre", estilo: "margin-top:8px" }, h("small", {}, "El agente recuerda lo que pida para las secciones siguientes; rechaza cambiar RA, contenidos mínimos u horas oficiales."), bRegenerar)),
        vivo, h("div", { clase: "fila fin", estilo: "margin-top:14px" }, bGuardar, bAprobar));
    } else {
      tarjeta.append(vistaContenido(sec.contenido));
      if (sec.estado === "aprobada" && pausa.tipo !== "revision_seccion") {
        tarjeta.append(h("div", { clase: "fila fin" }, h("button", { clase: "boton secundario chico", onclick: (e) => conCarga(e.target, async () => { await api("POST", `/silabos/${s.id}/secciones/${sec.clave}/reabrir`); recargar(); }) }, "Reabrir con el agente")));
      }
    }
    if (sec.historial && sec.historial.length > 1) {
      tarjeta.append(h("details", { estilo: "margin-top:12px" }, h("summary", {}, `Historial (${sec.historial.length} versiones)`),
        h("ul", {}, sec.historial.map((v) => h("li", {}, `v${v.n} · ${v.origen} · ${fechaCorta(v.creado)}${v.indicacion ? ` · pidió: «${v.indicacion}»` : ""}`)))));
    }
    centro.append(tarjeta);

    derecha.replaceChildren(
      h("div", { clase: "tarjeta" }, h("h3", {}, "Fuentes de esta sección"), listaCitas(sec.citas)),
      h("div", { clase: "tarjeta" }, h("h3", {}, "Validación"), listaHallazgos(s.hallazgos.filter((x) => x.seccion === sec.clave), s.id, recargar)),
      h("div", { clase: "tarjeta" }, h("h3", {}, "Lo que el agente recuerda"),
        s.preferencias.length ? h("ul", { clase: "memoria" }, s.preferencias.map((p) => h("li", {}, p))) : h("p", { clase: "suave", estilo: "font-size:13px" }, "Aún nada: pídale lo que quiera en la conversación.")));
  }

  cuerpo.replaceChildren(h("div", { clase: "espacio-trabajo" },
    h("div", { clase: "columna-pegada" }, h("div", { clase: "tarjeta", estilo: "padding:10px" }, pasos)),
    centro, derecha));
  pintar();
}

// --- PIS -----------------------------------------------------------------------------------

const GRUPOS_PIS = [
  ["1. Identificación del PIS", ["titulo", "carrera", "periodo", "nivel", "equipo_docente"]],
  ["2-3. Problema del contexto y justificación", ["problema", "contexto", "justificacion", "pregunta_reto", "delimitacion"]],
  ["4. Propósito", ["proposito"]],
  ["5-7. Competencias, PF participantes y matriz de articulación", ["competencias", "pf_participantes", "articulacion", "aporte_este_pf"]],
  ["8. Evidencia integradora", ["evidencia_integradora", "aportes_integrados", "criterios_logro"]],
  ["9. Investigación y fases de la actuación", ["investigacion", "etapas"]],
  ["10. Plan de actividades y cronograma", ["cronograma"]],
  ["11. Roles y responsabilidades", ["roles"]],
  ["12-16. Evaluación, recursos, socialización, reflexión e impacto", ["evaluacion", "recursos", "socializacion", "reflexion", "impacto", "prueba_interdisciplinariedad"]],
];

async function pestanaPIS(s, cuerpo) {
  const pis = await api("GET", `/web/silabos/${s.id}/pis`);
  const recargar = () => vistaSilabo(s.id, "pis");
  const editores = [];
  const grupos = GRUPOS_PIS.map(([titulo, campos]) => {
    const parcial = Object.fromEntries(campos.map((c) => [c, pis.contenido[c]]));
    const e = crearEditor(parcial, {});
    editores.push(e);
    return h("details", { clase: "tarjeta", open: titulo.startsWith("1") || titulo.startsWith("2") || titulo.startsWith("5") },
      h("summary", { estilo: "cursor:pointer" }, h("h3", { estilo: "display:inline" }, titulo)), h("div", { estilo: "margin-top:12px" }, e.el));
  });
  const leer = () => Object.assign({}, ...editores.map((e) => e.leer()));
  const indicacion = h("textarea", { rows: 2, placeholder: "Opcional: «enfócalo en la gestión de residuos de la sede», «solo con Bases de Datos y Redes», «más semanas para la validación»…" });
  const parte = h("select", {}, h("option", { value: "" }, "Todo el PIS"), pis.partes.map((p) => h("option", { value: p }, etiquetaDe(p))));
  const bGenerar = h("button", { clase: "boton" }, pis.estado === "vacio" ? "Proponer el PIS con el agente" : "Rehacer con el agente");
  bGenerar.onclick = () => conCarga(bGenerar, async () => {
    await api("POST", `/web/silabos/${s.id}/pis/generar`, { indicacion: indicacion.value, parte: parte.value || null });
    avisar(parte.value ? `El agente rehízo «${etiquetaDe(parte.value)}»` : "El agente propuso el PIS", "exito");
    recargar();
  }, "El agente está redactando…");
  const bGuardar = h("button", { clase: "boton exito" }, "Guardar mis cambios");
  bGuardar.onclick = () => conCarga(bGuardar, async () => { await api("PUT", `/web/silabos/${s.id}/pis`, { contenido: leer() }); avisar("PIS guardado", "exito"); recargar(); });
  const ultimo = pis.historial[pis.historial.length - 1];
  const cumplidos = pis.criterios.filter((c) => c.cumple).length;
  cuerpo.replaceChildren(h("div", { clase: "rejilla", estilo: "grid-template-columns:minmax(0,1fr) 320px;align-items:start" },
    h("div", {},
      h("div", { clase: "tarjeta" },
        h("div", { clase: "fila entre" }, h("h2", {}, "Proyecto Interdisciplinario Socioformativo"),
          pastilla(pis.estado === "vacio" ? "Sin empezar" : pis.estado === "propuesto" ? "Propuesto por el agente" : "Editado por usted", pis.estado === "editado" ? "verde" : "morado")),
        h("p", { clase: "media" }, "El PIS va aparte de las secciones: el agente lo propone con la Guía de construcción de PIS y los PF del mismo nivel de la malla, y usted lo cambia cuando quiera. Lo que aporte este PF se lleva a la sección 7.2 y el PIS sale como anexo del sílabo."),
        ultimo && ultimo.nota ? h("div", { clase: "nota-agente" }, h("b", {}, ultimo.origen === "agente" ? "El agente: " : "Último cambio: "), ultimo.nota) : null,
        h("div", { clase: "conversacion" }, h("b", {}, "Pedirle al agente"), indicacion,
          h("div", { clase: "fila entre", estilo: "margin-top:8px" }, h("label", { clase: "fila" }, h("small", {}, "Qué rehacer:"), parte), bGenerar))),
      ...grupos,
      h("div", { clase: "fila fin", estilo: "margin-top:14px" }, bGuardar)),
    h("div", { clase: "columna-pegada" },
      h("div", { clase: "tarjeta" }, h("h3", {}, `Criterios de la guía (${cumplidos}/${pis.criterios.length})`),
        ...pis.criterios.map((c) => h("div", { clase: `criterio ${c.cumple ? "si" : "no"}` }, h("span", { clase: "icono" }, c.cumple ? "✓" : "!"),
          h("span", {}, c.criterio, c.detalle ? h("small", { clase: "suave" }, c.detalle) : null)))),
      h("div", { clase: "tarjeta" }, h("h3", {}, "Fuentes de la guía"), listaCitas(pis.citas)))));
}

// --- documento final editable ------------------------------------------------------------------

async function pestanaDocumento(s, cuerpo) {
  const doc = await api("GET", `/web/silabos/${s.id}/documento`);
  const recargar = () => vistaSilabo(s.id, "documento");
  const enRevision = s.pausa.tipo === "revision_seccion";
  const editores = {};
  let cambios = false;
  const marca = h("span", { clase: "pastilla ambar", hidden: true }, "Cambios sin guardar");
  const alCambiar = () => { cambios = true; marca.hidden = false; };
  const hoja = h("div", { clase: "hoja" },
    h("div", { clase: "portada" }, h("img", { src: "/static/logo-color.png", alt: "", estilo: "height:46px" }),
      h("h2", { estilo: "margin-top:10px" }, `${estado.sistema.formato}`), h("p", { clase: "media" }, `${doc.silabo.asignatura.codigo} · ${doc.silabo.asignatura.nombre} · Periodo ${doc.silabo.periodo}`)));
  for (const sec of doc.secciones) {
    const e = crearEditor(sec.contenido, { oficiales: sec.oficiales, esquema: sec.esquema, soloLectura: enRevision, alCambiar });
    editores[sec.clave] = { editor: e, original: JSON.stringify(sec.contenido) };
    const [et, color] = ESTADOS_SECCION[sec.estado] || [sec.estado, ""];
    hoja.append(h("h2", { clase: "seccion" }, sec.titulo, " ", pastilla(et, color)), e.el);
  }
  const desbloqueo = h("input", { type: "checkbox" });
  desbloqueo.onchange = () => {
    if (desbloqueo.checked && !confirm("Los datos oficiales (RA, contenidos mínimos, horas) vienen de la malla aprobada por el CES. Si los cambia, la verificación lo señalará y deberá justificarlo ante el Comité Curricular. ¿Desbloquear?")) { desbloqueo.checked = false; return; }
    Object.values(editores).forEach(({ editor }) => editor.desbloquear(desbloqueo.checked));
  };
  const bGuardar = h("button", { clase: "boton exito", disabled: enRevision }, "Guardar correcciones");
  bGuardar.onclick = () => conCarga(bGuardar, async () => {
    const secciones = {};
    for (const [clave, { editor, original }] of Object.entries(editores)) {
      const v = editor.leer();
      if (JSON.stringify(v) !== original) secciones[clave] = v;
    }
    if (!Object.keys(secciones).length) { avisar("No hay cambios que guardar"); return; }
    const r = await api("PUT", `/web/silabos/${s.id}/documento`, { secciones });
    avisar(`Se guardaron ${r.cambiadas.length} sección(es) y se verificó el sílabo`, "exito");
    cambios = false;
    recargar();
  }, "Guardando y verificando…");
  window.onbeforeunload = () => (cambios ? "Hay cambios sin guardar" : undefined);
  cuerpo.replaceChildren(h("div", { clase: "rejilla", estilo: "grid-template-columns:minmax(0,1fr) 300px;align-items:start" },
    h("div", { clase: "documento" },
      enRevision ? h("div", { clase: "alerta info" }, "El agente todavía está revisando secciones con usted. Termine en la pestaña ", h("a", { href: `#/silabo/${s.id}/agente` }, "Agente por secciones"), "; mientras tanto el documento se muestra solo para leer.") : null,
      hoja),
    h("div", { clase: "columna-pegada" },
      h("div", { clase: "tarjeta" }, h("h3", {}, "Corregir el documento"),
        h("p", { clase: "media", estilo: "font-size:14px" }, "Edite cualquier parte del sílabo directamente. Al guardar, cada sección cambiada queda como una versión suya y el sílabo se vuelve a verificar."),
        h("label", { clase: "fila", estilo: "margin:8px 0 12px" }, desbloqueo, h("span", {}, "Permitir editar datos oficiales 🔒")),
        h("div", { clase: "fila entre" }, marca, bGuardar),
        h("div", { clase: "separador" }),
        h("a", { clase: "boton naranja", href: `#/silabo/${s.id}/exportar`, estilo: "width:100%;justify-content:center" }, "Ir a exportar")),
      h("div", { clase: "tarjeta" }, h("h3", {}, "Verificación"), listaHallazgos(doc.hallazgos, s.id, recargar)))));
}

// --- exportar ----------------------------------------------------------------------------------

async function pestanaExportar(s, cuerpo) {
  const pendientes = s.secciones.filter((x) => x.estado !== "aprobada");
  const bloqueantes = s.hallazgos.filter((x) => !x.resuelto && x.severidad === "bloqueante");
  const listo = !pendientes.length && !bloqueantes.length;
  const boton = (texto, formato, borrador, clase) => {
    const b = h("button", { clase: `boton ${clase}`, disabled: !borrador && !listo }, texto);
    b.onclick = () => conCarga(b, async () => {
      const nombre = await descargar(`/silabos/${s.id}/exportar?formato=${formato}&borrador=${borrador}`);
      avisar(`Descargado: ${nombre}`, "exito");
      if (!borrador) vistaSilabo(s.id, "exportar");
    }, "Generando…");
    return b;
  };
  cuerpo.replaceChildren(h("div", { clase: "rejilla dos" },
    h("div", { clase: "tarjeta" }, h("h2", {}, "Versión final"),
      h("p", { clase: "media" }, "Requiere todas las secciones aprobadas y ninguna observación bloqueante. Incluye el PIS como anexo y genera aparte el anexo de trazabilidad (fuentes por sección)."),
      listo ? h("div", { clase: "alerta exito" }, "El sílabo está listo para exportarse.") : h("div", {},
        pendientes.length ? h("div", { clase: "alerta advertencia" }, `Secciones sin aprobar: ${pendientes.map((x) => x.titulo).join(", ")}`) : null,
        bloqueantes.map((x) => h("div", { clase: "alerta bloqueante" }, h("b", {}, x.regla), " · ", x.mensaje))),
      h("div", { clase: "fila" }, boton("Descargar Word (.docx)", "docx", false, ""), boton("Descargar PDF", "pdf", false, "secundario"))),
    h("div", { clase: "tarjeta" }, h("h2", {}, "Borrador de trabajo"),
      h("p", { clase: "media" }, "Se exporta siempre, marcado como borrador y con las observaciones pendientes al final. Útil para compartirlo con su coordinación antes de cerrarlo."),
      h("div", { clase: "fila" }, boton("Borrador Word", "docx", true, "secundario"), boton("Borrador PDF", "pdf", true, "secundario")),
      h("div", { clase: "separador" }),
      h("small", {}, "El formato de exportación es provisional (Propuesta de sílabo UTI 2026) hasta contar con la plantilla oficial."))));
}

// --- malla -------------------------------------------------------------------------------------

async function vistaMalla(id) {
  const m = await api("GET", `/web/mallas/${id}`);
  const niveles = [...new Set(m.lista.map((a) => a.nivel))].sort((a, b) => a - b);
  const columna = h("div", {},
    m.avisos.map((a) => h("div", { clase: "alerta advertencia" }, a)),
    !m.lista.length ? h("div", { clase: "tarjeta vacio" }, "Esta malla no trae la tabla de asignaturas. ", esAdmin() ? "Puede registrarlas a mano desde Administración › Mallas." : "") : null,
    niveles.map((n) => h("div", { clase: "nivel" }, h("h3", {}, `Nivel ${n}`),
      m.lista.filter((a) => a.nivel === n).map((a) => tarjetaAsignatura(a, () => vistaMalla(id))))));
  principal(
    h("div", { clase: "encabezado-vista" },
      h("div", {}, h("div", { clase: "migas" }, "Mallas del CES"), h("h1", {}, m.nombre),
        h("p", {}, `${m.archivo} · ${m.paginas} páginas · ${m.asignaturas} asignaturas · `, pastilla(m.estado === "publicada" ? "Publicada" : `${m.revisadas} de ${m.asignaturas} revisadas`, m.estado === "publicada" ? "verde" : "ambar"))),
      esAdmin() && m.estado !== "publicada" ? h("button", { clase: "boton", onclick: (e) => conCarga(e.target, async () => { await api("POST", `/web/mallas/${id}/publicar`); estado.mallas = await api("GET", "/web/mallas"); pintarMallas(); vistaMalla(id); }) }, "Publicar malla") : null),
    h("div", { clase: "malla-vista" }, columna,
      h("div", { clase: "columna-pegada" }, h("iframe", { clase: "visor-pdf", src: `/web/mallas/${id}/pdf#view=FitH`, title: `PDF de la malla ${m.nombre}` }))));
}

function tarjetaAsignatura(a, alCambiar) {
  const f = a.ficha || {};
  return h("details", { clase: "asignatura" },
    h("summary", {}, h("span", {}, h("b", {}, a.nombre), h("br"), h("small", {}, `${a.codigo} · ${a.horas} h (${f.horas_contacto ?? 0} contacto · ${f.horas_practicas ?? 0} práctica · ${f.horas_autonomas ?? 0} autónoma)`)),
      a.revisada ? pastilla("Revisada", "verde") : a.ficha_valida ? pastilla("Por revisar", "ambar") : pastilla("Incompleta", "rojo")),
    a.avisos.length ? h("div", { clase: "alerta advertencia", estilo: "margin-top:8px;font-size:13px" }, a.avisos.join(" ")) : null,
    h("b", {}, "Resultados de aprendizaje"), h("ol", {}, (f.resultados_aprendizaje || []).map((r) => h("li", {}, r.enunciado))),
    h("b", {}, "Contenidos mínimos"), h("ul", {}, (f.contenidos_minimos || []).map((c) => h("li", {}, c))),
    h("div", { clase: "fila fin" },
      esAdmin() ? h("button", { clase: "boton secundario chico", onclick: () => editarFicha(a, alCambiar) }, "Editar ficha") : null,
      a.ficha_valida ? h("a", { clase: "boton chico", href: `#/nuevo/${a.id}` }, "Crear sílabo con esta asignatura") : null));
}

function editarFicha(a, alCambiar) {
  const ficha = Object.assign({ resultados_aprendizaje: [], contenidos_minimos: [], horas_contacto: 0, horas_practicas: 0, horas_autonomas: 0,
    unidad_organizacion: "", modalidad: "Presencial", competencia_especifica: "", facultad: "" }, a.ficha);
  delete ficha.pagina_ces; delete ficha.bibliografia; delete ficha.correquisitos; delete ficha.desempeno_central;
  delete ficha.metacompetencia; delete ficha.pis_periodo; delete ficha.microcredencial;
  ficha.competencia_especifica = ficha.competencia_especifica || "";
  const nombre = h("input", { type: "text", value: a.nombre });
  const codigo = h("input", { type: "text", value: a.codigo });
  const nivel = h("input", { type: "number", value: a.nivel, min: 1, max: 12 });
  const editor = crearEditor(ficha, {});
  const bGuardar = h("button", { clase: "boton secundario" }, "Guardar");
  const bRevisada = h("button", { clase: "boton exito" }, "Guardar y marcar como revisada");
  const cerrar = modal(`Ficha curricular · ${a.codigo}`, h("div", {},
    h("p", { clase: "media" }, "Compare con el PDF del CES y corrija lo que la extracción automática no leyó bien. Una ficha revisada es la que los docentes usarán como dato oficial."),
    h("div", { clase: "rejilla tres" }, h("label", { clase: "campo" }, h("span", {}, "Nombre"), nombre), h("label", { clase: "campo" }, h("span", {}, "Código"), codigo), h("label", { clase: "campo" }, h("span", {}, "Nivel"), nivel)),
    editor.el, h("div", { clase: "fila fin" }, bGuardar, bRevisada)), { ancho: true });
  const guardar = (revisada) => async () => {
    const f = editor.leer();
    if (!f.competencia_especifica) f.competencia_especifica = null;
    await api("PUT", `/web/asignaturas/${a.id}`, { nombre: nombre.value, codigo: codigo.value, nivel: Number(nivel.value), ficha: f, revisada });
    avisar("Ficha guardada", "exito");
    cerrar();
    estado.mallas = await api("GET", "/web/mallas");
    pintarMallas();
    alCambiar && alCambiar();
  };
  bGuardar.onclick = () => conCarga(bGuardar, guardar(null));
  bRevisada.onclick = () => conCarga(bRevisada, guardar(true));
}

// --- administración --------------------------------------------------------------------------

function encabezadoAdmin(titulo, descripcion, ...acciones) {
  return h("div", { clase: "encabezado-vista" }, h("div", {}, h("div", { clase: "migas" }, "Administración"), h("h1", {}, titulo), h("p", {}, descripcion)), h("div", { clase: "fila" }, ...acciones));
}

function mostrarClaves(cuentas) {
  const conClave = cuentas.filter((c) => c.clave_temporal);
  if (!conClave.length) return;
  modal("Contraseñas temporales", h("div", {},
    h("p", { clase: "media" }, "Entréguelas a cada docente; podrán cambiarlas desde su menú. No se volverán a mostrar."),
    h("table", { clase: "tabla" }, h("tbody", {}, conClave.map((c) => h("tr", {}, h("td", {}, c.nombre), h("td", {}, c.correo), h("td", {}, h("span", { clase: "clave-temporal" }, c.clave_temporal)))))),
    h("div", { clase: "fila fin" }, h("button", { clase: "boton secundario", onclick: () => navigator.clipboard.writeText(conClave.map((c) => `${c.nombre}\t${c.correo}\t${c.clave_temporal}`).join("\n")).then(() => avisar("Copiado")) }, "Copiar todo"))));
}

async function vistaDocentes() {
  const cuentas = await api("GET", "/web/usuarios");
  const carreras = estado.mallas.map((m) => m.carrera);
  const selCarrera = () => h("select", {}, h("option", { value: "" }, "(todas)"), carreras.map((c) => h("option", { value: c }, c)));
  const nombre = h("input", { type: "text", placeholder: "Nombre y apellido" });
  const correo = h("input", { type: "email", placeholder: "docente@uti.edu.ec" });
  const carrera = selCarrera();
  const rol = h("select", {}, Object.entries(ROLES).map(([k, v]) => h("option", { value: k }, v)));
  const bCrear = h("button", { clase: "boton" }, "Crear cuenta");
  bCrear.onclick = () => conCarga(bCrear, async () => {
    const r = await api("POST", "/web/usuarios", { nombre: nombre.value, correo: correo.value, carrera: carrera.value || null, rol: rol.value });
    mostrarClaves([r]); vistaDocentes();
  });
  const lote = h("textarea", { rows: 5, placeholder: "Una cuenta por línea: Nombre; correo; carrera\nAna Pérez; aperez@uti.edu.ec; ITI\nLuis Vera; lvera@uti.edu.ec; IND" });
  const bLote = h("button", { clase: "boton secundario" }, "Crear cuentas en lote");
  bLote.onclick = () => conCarga(bLote, async () => {
    const r = await api("POST", "/web/usuarios/lote", { texto: lote.value });
    if (r.errores.length) avisar(r.errores.join(" · "), "error");
    mostrarClaves(r.creadas); vistaDocentes();
  });
  const filas = cuentas.map((u) => h("tr", {},
    h("td", {}, h("b", {}, u.nombre), h("br"), h("small", {}, u.correo)),
    h("td", {}, ROLES[u.rol] || u.rol), h("td", {}, u.carrera || "—"), h("td", {}, u.silabos),
    h("td", {}, u.activo ? pastilla("Activa", "verde") : pastilla("Desactivada", "rojo")),
    h("td", { estilo: "text-align:right;white-space:nowrap" },
      h("button", { clase: "boton secundario chico", onclick: (e) => conCarga(e.target, async () => { const r = await api("PATCH", `/web/usuarios/${u.id}`, { restablecer_clave: true }); mostrarClaves([r]); }) }, "Nueva contraseña"), " ",
      h("button", { clase: `boton chico ${u.activo ? "peligro" : "secundario"}`, onclick: (e) => conCarga(e.target, async () => { await api("PATCH", `/web/usuarios/${u.id}`, { activo: !u.activo }); vistaDocentes(); }) }, u.activo ? "Desactivar" : "Activar"))));
  principal(encabezadoAdmin("Cuentas", "Su cuenta de administrador y una cuenta por docente. Las contraseñas se generan y se muestran una sola vez."),
    h("div", { clase: "rejilla dos" },
      h("div", { clase: "tarjeta" }, h("h2", {}, "Nueva cuenta"),
        h("div", { clase: "rejilla dos" }, h("label", { clase: "campo" }, h("span", {}, "Nombre"), nombre), h("label", { clase: "campo" }, h("span", {}, "Correo"), correo),
          h("label", { clase: "campo" }, h("span", {}, "Carrera"), carrera), h("label", { clase: "campo" }, h("span", {}, "Rol"), rol)),
        h("div", { clase: "fila fin" }, bCrear)),
      h("div", { clase: "tarjeta" }, h("h2", {}, "Varias cuentas a la vez"), lote, h("div", { clase: "fila fin", estilo: "margin-top:8px" }, bLote))),
    h("div", { clase: "tarjeta" }, h("div", { clase: "envoltura-tabla" }, h("table", { clase: "tabla" },
      h("thead", {}, h("tr", {}, ["Persona", "Rol", "Carrera", "Sílabos", "Estado", ""].map((t) => h("th", {}, t)))), h("tbody", {}, filas)))));
}

async function vistaDocumentos() {
  const docs = await api("GET", "/documentos");
  const archivo = h("input", { type: "file", accept: ".pdf,.docx" });
  const titulo = h("input", { type: "text" });
  const tipo = h("select", {}, Object.entries(TIPOS_DOC).map(([k, v]) => h("option", { value: k }, v)));
  const carrera = h("select", {}, h("option", { value: "TODAS" }, "TODAS (institucional)"), estado.mallas.map((m) => h("option", { value: m.carrera }, m.carrera)), h("option", { value: "ITI" }, "ITI"));
  const version = h("input", { type: "text", placeholder: "p. ej. 2026-11" });
  const fecha = h("input", { type: "date", value: new Date().toISOString().slice(0, 10) });
  archivo.onchange = async () => {
    if (!archivo.files[0]) return;
    const datos = new FormData(); datos.append("archivo", archivo.files[0]);
    try { const r = await api("POST", "/web/documentos/vista-previa", datos, { formulario: true }); if (!titulo.value) titulo.value = r.titulo_sugerido; } catch (_) { /* opcional */ }
  };
  const bSubir = h("button", { clase: "boton" }, "Cargar, indexar y anunciar");
  bSubir.onclick = () => conCarga(bSubir, async () => {
    if (!archivo.files[0]) throw new Error("Elija un archivo PDF o DOCX");
    const datos = new FormData();
    datos.append("archivo", archivo.files[0]); datos.append("titulo", titulo.value); datos.append("tipo", tipo.value);
    datos.append("carrera", carrera.value); datos.append("version", version.value); datos.append("fecha_vigencia", fecha.value);
    const r = await api("POST", "/documentos", datos, { formulario: true });
    avisar(`«${r.titulo}» indexado (${r.fragmentos} fragmentos). Se publicó la noticia.`, "exito");
    await cargarNoticias(false); vistaDocumentos();
  }, "Indexando…");
  const filas = docs.map((d) => h("tr", {},
    h("td", {}, h("b", {}, d.titulo), h("br"), h("small", {}, d.archivo)),
    h("td", {}, TIPOS_DOC[d.tipo] || d.tipo), h("td", {}, d.carrera), h("td", {}, d.version), h("td", {}, d.fecha_vigencia),
    h("td", {}, d.fragmentos), h("td", {}, d.estado === "vigente" ? pastilla("Vigente", "verde") : pastilla("Obsoleto", "rojo")),
    h("td", { estilo: "text-align:right" }, h("button", { clase: "boton secundario chico", onclick: (e) => conCarga(e.target, async () => {
      await api("PATCH", `/documentos/${d.id}`, { estado: d.estado === "vigente" ? "obsoleto" : "vigente" }); await cargarNoticias(false); vistaDocumentos();
    }) }, d.estado === "vigente" ? "Marcar obsoleto" : "Marcar vigente"))));
  principal(encabezadoAdmin("Documentos del corpus", "Lo que el agente consulta (RAG). Una versión nueva de un documento deja la anterior como obsoleta y se anuncia en Noticias con el resumen de los cambios."),
    h("div", { clase: "tarjeta" }, h("h2", {}, "Cargar un documento"),
      h("div", { clase: "rejilla tres" },
        h("label", { clase: "campo" }, h("span", {}, "Archivo (PDF o DOCX)"), archivo), h("label", { clase: "campo" }, h("span", {}, "Título"), titulo), h("label", { clase: "campo" }, h("span", {}, "Tipo"), tipo),
        h("label", { clase: "campo" }, h("span", {}, "Carrera"), carrera), h("label", { clase: "campo" }, h("span", {}, "Versión"), version), h("label", { clase: "campo" }, h("span", {}, "Vigente desde"), fecha)),
      h("p", { clase: "ayuda" }, "Para que se reconozca como versión nueva de un documento existente, use el mismo título, tipo y carrera."),
      h("div", { clase: "fila fin" }, bSubir)),
    h("div", { clase: "tarjeta" }, h("div", { clase: "envoltura-tabla" }, h("table", { clase: "tabla" },
      h("thead", {}, h("tr", {}, ["Documento", "Tipo", "Carrera", "Versión", "Vigencia", "Fragmentos", "Estado", ""].map((t) => h("th", {}, t)))), h("tbody", {}, filas)))));
}

async function vistaAdminMallas() {
  estado.mallas = await api("GET", "/web/mallas");
  pintarMallas();
  const bCarpeta = h("button", { clase: "boton naranja" }, "Importar carpeta MALLAS");
  bCarpeta.onclick = () => conCarga(bCarpeta, async () => {
    const r = await api("POST", "/web/mallas/importar-carpeta");
    avisar(`Mallas importadas: ${r.map((m) => `${m.carrera} (${m.asignaturas})`).join(", ")}`, "exito");
    await cargarNoticias(false); vistaAdminMallas();
  }, "Extrayendo e indexando (puede tardar)…");
  const archivo = h("input", { type: "file", accept: ".pdf" });
  const bSubir = h("button", { clase: "boton secundario" }, "Subir malla PDF");
  bSubir.onclick = () => conCarga(bSubir, async () => {
    if (!archivo.files[0]) throw new Error("Elija el PDF de la malla del CES");
    const datos = new FormData(); datos.append("archivo", archivo.files[0]);
    await api("POST", "/web/mallas", datos, { formulario: true });
    await cargarNoticias(false); vistaAdminMallas();
  }, "Extrayendo…");
  const asignaturas = await api("GET", "/asignaturas");
  const ejemplo = asignaturas.filter((a) => a.origen === "ejemplo");
  const codigo = h("input", { type: "text", placeholder: "ELE-0101" });
  const nombre = h("input", { type: "text" });
  const carrera = h("select", {}, estado.mallas.map((m) => h("option", { value: m.carrera }, m.carrera)));
  const nivel = h("input", { type: "number", value: 1, min: 1, max: 12 });
  const bNueva = h("button", { clase: "boton secundario" }, "Registrar asignatura");
  bNueva.onclick = () => conCarga(bNueva, async () => {
    const malla = estado.mallas.find((m) => m.carrera === carrera.value);
    const a = await api("POST", "/web/asignaturas", { codigo: codigo.value, nombre: nombre.value, carrera: carrera.value, nivel: Number(nivel.value), malla_id: malla ? malla.id : null });
    estado.mallas = await api("GET", "/web/mallas"); pintarMallas(); editarFicha(a, vistaAdminMallas);
  });
  principal(encabezadoAdmin("Mallas del CES", "Cada PDF se indexa para el agente, se transcribe su perfil de egreso y se extraen las asignaturas con RA, contenidos mínimos y horas. Revise cada ficha antes de publicar.", bCarpeta),
    h("div", { clase: "rejilla tres" }, estado.mallas.map((m) => h("div", { clase: "tarjeta" },
      h("div", { clase: "fila entre" }, h("span", { clase: "malla-sigla" }, m.carrera), m.estado === "publicada" ? pastilla("Publicada", "verde") : pastilla("En revisión", "ambar")),
      h("h3", { estilo: "margin-top:10px" }, m.nombre), h("p", { clase: "media" }, `${m.asignaturas} asignaturas · ${m.revisadas} revisadas · niveles ${m.niveles.join(", ") || "—"}`),
      m.avisos.map((a) => h("div", { clase: "alerta advertencia", estilo: "font-size:13px" }, a)),
      h("a", { clase: "boton chico", href: `#/malla/${m.id}` }, "Revisar asignaturas")))),
    h("div", { clase: "rejilla dos", estilo: "margin-top:14px" },
      h("div", { clase: "tarjeta" }, h("h2", {}, "Subir otra malla"), h("p", { clase: "media" }, "PDF generado por la plataforma del CES. Se reconocen Tecnologías de la Información, Industrial y Eléctrica."), archivo, h("div", { clase: "fila fin", estilo: "margin-top:8px" }, bSubir)),
      h("div", { clase: "tarjeta" }, h("h2", {}, "Registrar una asignatura a mano"), h("p", { clase: "media" }, "Para mallas que no traen la tabla de asignaturas (p. ej. Eléctrica)."),
        h("div", { clase: "rejilla dos" }, h("label", { clase: "campo" }, h("span", {}, "Código"), codigo), h("label", { clase: "campo" }, h("span", {}, "Nombre"), nombre),
          h("label", { clase: "campo" }, h("span", {}, "Carrera"), carrera), h("label", { clase: "campo" }, h("span", {}, "Nivel"), nivel)),
        h("div", { clase: "fila fin" }, bNueva))),
    ejemplo.length ? h("div", { clase: "tarjeta plana" }, h("h3", {}, "Catálogo de ejemplo"), h("p", { clase: "media" }, `${ejemplo.length} asignaturas ficticias del prototipo (${ejemplo.map((a) => a.codigo).join(", ")}). Sirven para probar; no son datos oficiales.`)) : null);
}

async function vistaAdminNoticias() {
  const fuentes = await api("GET", "/web/fuentes");
  const titulo = h("input", { type: "text" });
  const cuerpoN = h("textarea", { rows: 4 });
  const categoria = h("select", {}, Object.entries(CATEGORIAS).map(([k, [v]]) => h("option", { value: k, selected: k === "aviso" }, v)));
  const carrera = h("select", {}, h("option", { value: "TODAS" }, "Todas las carreras"), estado.mallas.map((m) => h("option", { value: m.carrera }, m.carrera)));
  const importante = h("input", { type: "checkbox" });
  const bPublicar = h("button", { clase: "boton" }, "Publicar");
  bPublicar.onclick = () => conCarga(bPublicar, async () => {
    await api("POST", "/web/noticias", { titulo: titulo.value, cuerpo: cuerpoN.value, categoria: categoria.value, carrera: carrera.value, importante: importante.checked });
    avisar("Noticia publicada", "exito"); await cargarNoticias(false); vistaAdminNoticias();
  });
  const fNombre = h("input", { type: "text", placeholder: "Noticias UTI" });
  const fUrl = h("input", { type: "url", placeholder: "https://…" });
  const fTipo = h("select", {}, h("option", { value: "pagina" }, "Página web (avisa si cambia)"), h("option", { value: "rss" }, "Canal RSS / Atom (cada entrada nueva)"));
  const fCarrera = h("select", {}, h("option", { value: "TODAS" }, "Todas"), estado.mallas.map((m) => h("option", { value: m.carrera }, m.carrera)));
  const bFuente = h("button", { clase: "boton secundario" }, "Añadir fuente");
  bFuente.onclick = () => conCarga(bFuente, async () => {
    await api("POST", "/web/fuentes", { nombre: fNombre.value, url: fUrl.value, tipo: fTipo.value, carrera: fCarrera.value });
    avisar("Fuente añadida: desde ahora se avisará de lo nuevo", "exito"); vistaAdminNoticias();
  }, "Leyendo la fuente…");
  const bRevisar = h("button", { clase: "boton naranja" }, "Revisar fuentes ahora");
  bRevisar.onclick = () => conCarga(bRevisar, async () => {
    const r = await api("POST", "/web/fuentes/revisar");
    avisar(`Revisión terminada: ${r.publicadas} noticia(s) nueva(s)`, "exito"); await cargarNoticias(false); vistaAdminNoticias();
  }, "Revisando…");
  principal(encabezadoAdmin("Noticias", `El agente publica solo cuando cambia un documento, llega una malla o una fuente externa trae algo nuevo (revisión cada ${estado.sistema.vigia_min} min). Aquí puede publicar avisos y elegir qué fuentes vigilar.`, bRevisar),
    h("div", { clase: "rejilla dos" },
      h("div", { clase: "tarjeta" }, h("h2", {}, "Publicar un aviso"),
        h("label", { clase: "campo" }, h("span", {}, "Título"), titulo), h("label", { clase: "campo" }, h("span", {}, "Texto"), cuerpoN),
        h("div", { clase: "rejilla dos" }, h("label", { clase: "campo" }, h("span", {}, "Categoría"), categoria), h("label", { clase: "campo" }, h("span", {}, "Para"), carrera)),
        h("label", { clase: "fila" }, importante, h("span", {}, "Destacar como importante")),
        h("div", { clase: "fila fin" }, bPublicar)),
      h("div", { clase: "tarjeta" }, h("h2", {}, "Fuentes que vigila el agente"),
        h("p", { clase: "media" }, "Páginas o canales RSS de la universidad y de otras universidades. Lo nuevo se resume y se relaciona con el corpus."),
        h("div", { clase: "rejilla dos" }, h("label", { clase: "campo" }, h("span", {}, "Nombre"), fNombre), h("label", { clase: "campo" }, h("span", {}, "Dirección"), fUrl),
          h("label", { clase: "campo" }, h("span", {}, "Tipo"), fTipo), h("label", { clase: "campo" }, h("span", {}, "Carrera"), fCarrera)),
        h("div", { clase: "fila fin" }, bFuente),
        h("div", { clase: "separador" }),
        fuentes.length ? h("table", { clase: "tabla" }, h("tbody", {}, fuentes.map((f) => h("tr", {},
          h("td", {}, h("b", {}, f.nombre), h("br"), h("small", {}, h("a", { href: f.url, target: "_blank", rel: "noopener" }, f.url))),
          h("td", {}, f.tipo === "rss" ? "RSS" : "Página", h("br"), h("small", {}, f.ultima_revision ? `revisada ${fechaCorta(f.ultima_revision)}` : "sin revisar"), f.ultimo_error ? h("div", { clase: "alerta bloqueante", estilo: "font-size:12px;margin:4px 0 0" }, f.ultimo_error) : null),
          h("td", { estilo: "text-align:right" }, h("button", { clase: "boton peligro chico", onclick: (e) => conCarga(e.target, async () => { await api("DELETE", `/web/fuentes/${f.id}`); vistaAdminNoticias(); }) }, "Quitar"))))))
          : h("p", { clase: "suave" }, "Todavía no hay fuentes externas."))),
    h("div", { clase: "tarjeta" }, h("h2", {}, "Publicadas"), h("table", { clase: "tabla" }, h("tbody", {}, estado.noticias.map((n) => h("tr", {},
      h("td", {}, h("b", {}, n.titulo), h("br"), h("small", {}, `${(CATEGORIAS[n.categoria] || [n.categoria])[0]} · ${n.origen} · ${fechaCorta(n.fecha)}`)),
      h("td", { estilo: "text-align:right" }, h("button", { clase: "boton peligro chico", onclick: (e) => conCarga(e.target, async () => {
        await api("DELETE", `/web/noticias/${n.id}`); estado.noticias = estado.noticias.filter((x) => x.id !== n.id); pintarNoticias(); vistaAdminNoticias();
      }) }, "Retirar"))))))));
}

async function vistaSistema() {
  estado.sistema = await api("GET", "/web/estado");
  const s = estado.sistema;
  const resultado = h("div", {});
  const bProbar = h("button", { clase: "boton" }, "Probar el modelo");
  bProbar.onclick = () => conCarga(bProbar, async () => {
    const r = await api("POST", "/web/modelo/probar");
    resultado.replaceChildren(h("div", { clase: "alerta exito" }, `Respondió ${r.modelo} en ${r.latencia_ms} ms${r.ttft_ms ? ` (primer token: ${r.ttft_ms} ms)` : ""}.`));
  }, "Llamando al modelo…");
  principal(encabezadoAdmin("Sistema", "Modelo de lenguaje, embeddings y registros para la evaluación."),
    h("div", { clase: "rejilla dos" },
      h("div", { clase: "tarjeta" }, h("h2", {}, "Modelo de lenguaje"),
        h("table", { clase: "tabla" }, h("tbody", {},
          h("tr", {}, h("td", {}, "Proveedor"), h("td", {}, h("b", {}, s.llm.proveedor))),
          h("tr", {}, h("td", {}, "Modelo"), h("td", {}, h("b", {}, s.llm.modelo))),
          h("tr", {}, h("td", {}, "Dónde corre"), h("td", {}, s.llm.destino)),
          h("tr", {}, h("td", {}, "Dirección"), h("td", {}, h("code", {}, s.llm.url || "—"))),
          h("tr", {}, h("td", {}, "Embeddings"), h("td", {}, `${s.embeddings.proveedor}${s.embeddings.modelo ? ` · ${s.embeddings.modelo}` : ""}`)),
          h("tr", {}, h("td", {}, "Documentos en el corpus"), h("td", {}, s.documentos)))),
        h("div", { clase: "fila", estilo: "margin-top:12px" }, bProbar), resultado),
      h("div", { clase: "tarjeta" }, h("h2", {}, "Cambiar a NVIDIA"),
        h("p", { clase: "media" }, "El modelo se elige en la configuración, no en la página:"),
        h("ol", { clase: "media" },
          h("li", {}, h("b", {}, "NVIDIA Build: "), "defina la variable ", h("code", {}, "NVIDIA_API_KEY"), " y arranque con ", h("code", {}, "SYLLABUSAI_CONFIG=config/config.nvidia.yaml"), "."),
          h("li", {}, h("b", {}, "NVIDIA Brev: "), "levante el NIM del modelo de 120B en la instancia y use ", h("code", {}, "config/config.brev.yaml"), " con ", h("code", {}, "SYLLABUSAI_LLM_URL=http://<instancia>:8000/v1"), ".")),
        h("div", { clase: "separador" }),
        h("h3", {}, "Registros para la evaluación"),
        h("p", { clase: "media" }, "Latencia, TTFT, tokens, consultas al recuperador y correcciones de los docentes (RF-50 a RF-54)."),
        h("button", { clase: "boton secundario", onclick: (e) => conCarga(e.target, () => descargar("/metricas/export", "GET")) }, "Descargar eventos (CSV)"))));
}

// --- inicio --------------------------------------------------------------------------------

arrancar().catch(() => pantallaAcceso());
