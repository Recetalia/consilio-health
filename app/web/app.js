/* Interfaz de consulta de Consilio.
   Vanilla, sin build: la app es un servicio, no un frontend, y meterle un
   toolchain de JS para dos pantallas sería costo sin beneficio.

   `i18n.js` se carga antes y aporta `T`, `t()`, `LANG`, `setLang()`. Sólo
   traduce la UI: nombres de fármaco y de patología resuelven su idioma acá
   (`mostrar()`, `condLabel()`); el texto clínico libre de AEMPS/openFDA no se
   traduce nunca, ver `notaFuenteIdioma()`.
   `condiciones-es.js` se carga antes y aporta `condEs` y `BUSQUEDA_ES_EN`. */

const $ = (id) => document.getElementById(id);
const selected = [];           // medicamentos a recetar
const alergias = [];           // fármacos a los que el paciente reaccionó
const patologias = [];         // patologías CIE-10 del paciente

const apiKey = () => localStorage.getItem("consilio_api_key") || "";
const headers = () => {
  const h = { "Content-Type": "application/json" };
  const k = apiKey();
  if (k) h["X-API-Key"] = k;
  return h;
};

// `label` se resuelve en el momento (no al cargar el módulo) para seguir al
// idioma elegido: SEV se referencia desde muchos lugares que corren después
// de un cambio de idioma.
const SEV = {
  major:    { get label() { return t("sev_major"); },    rank: 0 },
  moderate: { get label() { return t("sev_moderate"); }, rank: 1 },
  minor:    { get label() { return t("sev_minor"); },    rank: 2 },
  unknown:  { get label() { return t("sev_unknown"); },  rank: 3 },
};

// Nombre completo y corto de cada fuente, también dependientes del idioma.
const FUENTE_KEYS = ["aemps", "ddinter", "openfda", "medrt", "recetalia", "consilio", "perfil"];
const FUENTE = {};
const FUENTE_CORTA = {};
FUENTE_KEYS.forEach((k) => {
  Object.defineProperty(FUENTE, k, { enumerable: true, get: () => t(`fuente_${k}`) });
  Object.defineProperty(FUENTE_CORTA, k, { enumerable: true, get: () => t(`fuente_corta_${k}`) });
});

// Canónico (inglés, el de la base) -> nombre para mostrar en castellano. Se va
// llenando con lo que devuelve el buscador: la base tiene 728 sustancias del
// DNMA y 73 alias manuales, así que buena parte del vademécum uruguayo se
// muestra en su grafía local en vez de en inglés. En inglés se muestra
// siempre el canónico: por eso `mostrar()` mira `LANG`.
const NOMBRE_ES = {};
const mostrar = (n) => (LANG === "es" ? (NOMBRE_ES[n] || n) : n);

// Patologías: en castellano, la traducción manual de `condEs()` (o el
// original si no está traducida); en inglés, siempre el nombre MeSH
// original. Es la misma idea que `mostrar()`, para el otro catálogo.
const condLabel = (n) => (LANG === "es" ? condEs(n) : n);

// Idioma real del texto libre según la fuente que lo escribió. Sólo se marca
// para las dos fuentes con texto libre: AEMPS (castellano) y openFDA
// (inglés). El resto (DDInter, MED-RT, Consilio) no lleva `lang` ni aviso.
const FUENTE_TEXTO_IDIOMA = { aemps: "es", openfda: "en" };

// Nota que aclara cuándo un texto clínico quedó en un idioma distinto al de
// la interfaz. `idiomaTexto` es el idioma real del texto ("es" para AEMPS,
// "en" para openFDA); no se traduce el texto, sólo se avisa cuando no
// coincide con `LANG`.
function notaFuenteIdioma(idiomaTexto) {
  if (idiomaTexto === LANG) return "";
  return idiomaTexto === "en"
    ? `<p class="evidence-note">${t("nota_texto_ingles")}</p>`
    : `<p class="evidence-note" lang="es">${t("nota_texto_espanol")}</p>`;
}

// Receta de ejemplo: cada par de acá dispara algo distinto —una grave con
// texto, una por clase, una contra el perfil—, así se ve de qué es capaz sin
// que el usuario tenga que adivinar qué escribir. Se busca por el nombre en
// castellano (mismo endpoint que el autocompletado) para que las píldoras
// no aparezcan en inglés al cargar el ejemplo.
// Sólo medicamentos: el perfil del paciente es el otro ejemplo. Mezclarlos
// hacía que "Probar un ejemplo" dejara edad y función renal cargadas.
const EJEMPLO = {
  drugs: ["warfarina", "ibuprofeno", "simvastatina", "claritromicina"],
};

function toast(msg, ms = 4500) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

/* ---------------- autocompletado (reusable) ----------------
   `fetchFn` devuelve la lista; `toItem` la convierte en {id, name, extra}.
   Así el mismo widget sirve para fármacos y para patologías, que vienen de
   endpoints distintos y se muestran distinto. */

function wireSearch({ input, list, target, chips, onChange, fetchFn, renderItem, renderChip }) {
  let timer = null;

  input.addEventListener("input", (e) => {
    const q = e.target.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { list.hidden = true; return; }
    timer = setTimeout(() => run(q), 180);
  });

  input.addEventListener("keydown", (e) => {
    const items = [...list.querySelectorAll("li[data-id]")];
    if (!items.length) return;
    const cur = items.findIndex((li) => li.getAttribute("aria-selected") === "true");
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = e.key === "ArrowDown"
        ? Math.min(cur + 1, items.length - 1) : Math.max(cur - 1, 0);
      items.forEach((li, i) => li.setAttribute("aria-selected", i === next));
      items[next].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = cur >= 0 ? items[cur] : items[0];
      if (pick) add(JSON.parse(pick.dataset.item));
    } else if (e.key === "Escape") {
      list.hidden = true;
    }
  });

  async function run(q) {
    let data;
    try {
      data = await fetchFn(q);
    } catch (err) {
      if (err !== "handled") toast(t("toast_error_servicio"));
      return;
    }
    if (!data) return;

    const fresh = data.filter((r) => !target.some((s) => s.id === r.id));
    if (!fresh.length) {
      list.innerHTML = '<li class="empty">Sin resultados</li>';
      list.hidden = false;
      return;
    }
    list.innerHTML = fresh.map((r, i) => `
      <li data-id="${escapeAttr(r.id)}" data-item="${escapeAttr(JSON.stringify(r))}"
          role="option" aria-selected="${i === 0}">${renderItem(r)}</li>`).join("");
    list.querySelectorAll("li[data-id]").forEach((li) =>
      li.addEventListener("click", () => add(JSON.parse(li.dataset.item))));
    list.hidden = false;
  }

  function add(item) {
    if (!target.some((s) => s.id === item.id)) target.push(item);
    input.value = "";
    list.hidden = true;
    invalidateResults();
    render();
    input.focus();
  }

  function render() {
    chips.innerHTML = target.map((s) => `
      <li>${renderChip(s)}
        <button type="button" aria-label="Quitar ${escapeAttr(s.name)}"
                data-id="${escapeAttr(s.id)}">&times;</button>
      </li>`).join("");
    chips.querySelectorAll("button").forEach((b) =>
      b.addEventListener("click", () => {
        const i = target.findIndex((s) => String(s.id) === b.dataset.id);
        if (i >= 0) target.splice(i, 1);
        invalidateResults();
        render();
      }));
    onChange();
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search")) list.hidden = true;
  });

  return { render };
}

async function buscarFarmacos(q) {
  const r = await fetch(`/drugs/search?q=${encodeURIComponent(q)}&limit=10`,
                        { headers: headers() });
  if (!r.ok) { handleHttpError(r); throw "handled"; }
  const data = await r.json();
  return (data.results || []).map((x) => {
    // Se muestra el nombre castellano cuando lo hay, pero se MANDA el canónico:
    // es la clave con la que vuelven los hallazgos, y si mandáramos el de
    // mostrar habría que re-mapear la respuesta.
    if (x.name_es) NOMBRE_ES[x.name] = x.name_es;
    return { id: x.drug_id, name: x.name, name_es: x.name_es, rxcui: x.rxcui };
  });
}

async function buscarPatologias(q) {
  // El catálogo está en inglés. Si lo tecleado tiene un sinónimo conocido en
  // castellano se consulta también por él: sin esto, "hepática" no encuentra
  // "Diseases of liver", que es donde cuelgan 130 alertas.
  const norm = q.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const alt = BUSQUEDA_ES_EN[norm] ||
              Object.entries(BUSQUEDA_ES_EN).find(([es]) => es.startsWith(norm))?.[1];
  const qs = alt && alt !== norm ? [q, alt] : [q];

  // limit=15: con los descendientes CIE-10 (N18.1…N18.9, N18.30…) una familia
  // como N18 ya son 11 códigos; con 10 se cortaba el anclaje más específico.
  const respuestas = await Promise.all(qs.map(async (t) => {
    const r = await fetch(`/conditions/search?q=${encodeURIComponent(t)}&limit=15`,
                          { headers: headers() });
    if (!r.ok) { handleHttpError(r); throw "handled"; }
    return (await r.json()).results || [];
  }));

  const vistos = new Set();
  return respuestas.flat().filter((x) => {
    if (vistos.has(x.code)) return false;
    vistos.add(x.code);
    return true;
  }).map((x) => ({
    // El original (MeSH, inglés) se conserva sin tocar: en EN se muestra tal
    // cual, en ES se traduce recién al pintar, con `condLabel()`. `anchor_code`
    // viaja para el aviso sutil "evalúa como X" cuando el código elegido es un
    // descendiente (no dispara alerta propia, dispara la de su anclaje).
    id: x.code, name: x.name, code: x.code, alertas: x.alertas,
    anchor_code: x.anchor_code,
  })).slice(0, 15);
}

/* ---------------- desplegable propio ----------------
   El `<select>` nativo abre el popup del sistema operativo, que no se puede
   estilar: en macOS aparece con tipografía enorme, resaltado azul y despegado
   del campo. Se envuelve en un botón + lista propios.

   El `<select>` NO se elimina: queda oculto como fuente de verdad del valor y
   emite su `change` de siempre, así todo lo que ya lo escucha —el bloque de
   gestación, la invalidación de resultados, `perfil()`— sigue funcionando sin
   enterarse. Reemplazarlo del todo habría obligado a tocar seis lugares más. */

function enhanceSelect(sel, { compacto = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "select" + (compacto ? " compacto" : "");
  sel.parentNode.insertBefore(wrap, sel);
  wrap.appendChild(sel);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "select-btn";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  // El lector de pantalla pierde la etiqueta al ocultar el `<select>`: se la
  // copiamos al botón, que es lo que ahora recibe el foco.
  const etiqueta = sel.getAttribute("aria-label") ||
    document.querySelector(`label[for="${sel.id}"]`)?.textContent.trim();
  if (etiqueta) btn.setAttribute("aria-label", etiqueta);
  btn.innerHTML = '<span class="valor"></span><span class="caret"></span>';

  const list = document.createElement("ul");
  list.className = "select-list";
  list.setAttribute("role", "listbox");
  list.hidden = true;

  wrap.append(btn, list);

  const opciones = () => [...sel.options];

  function pintarBoton() {
    const o = sel.selectedOptions[0];
    const v = btn.querySelector(".valor");
    v.textContent = o ? o.textContent : "";
    // Una opción cuyo value es "" es el placeholder, no una elección.
    v.classList.toggle("vacio", !o || o.value === "");
    btn.disabled = sel.disabled;
  }

  function pintarLista() {
    list.innerHTML = opciones().map((o, i) => `
      <li role="option" data-i="${i}" aria-selected="${o.selected}"
          class="${o.selected ? "activo" : ""}">${escapeHtml(o.textContent)}</li>`).join("");
    list.querySelectorAll("li").forEach((li) =>
      li.addEventListener("click", () => elegir(Number(li.dataset.i))));
  }

  function abrir() {
    if (sel.disabled) return;
    pintarLista();
    list.hidden = false;
    wrap.classList.add("abierto");
    btn.setAttribute("aria-expanded", "true");
    const act = list.querySelector("li.activo") || list.firstElementChild;
    act?.scrollIntoView({ block: "nearest" });
  }

  function cerrar() {
    list.hidden = true;
    wrap.classList.remove("abierto");
    btn.setAttribute("aria-expanded", "false");
  }

  function elegir(i) {
    sel.selectedIndex = i;
    // `change` no se dispara solo al asignar por script: hay que emitirlo, y es
    // justamente de lo que cuelga el resto de la pantalla.
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    pintarBoton();
    cerrar();
    btn.focus();
  }

  function mover(paso) {
    const items = [...list.querySelectorAll("li")];
    if (!items.length) return;
    const cur = items.findIndex((li) => li.classList.contains("activo"));
    const next = Math.min(Math.max((cur < 0 ? 0 : cur) + paso, 0), items.length - 1);
    items.forEach((li, i) => li.classList.toggle("activo", i === next));
    items[next].scrollIntoView({ block: "nearest" });
  }

  btn.addEventListener("click", () => (list.hidden ? abrir() : cerrar()));
  btn.addEventListener("keydown", (e) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      if (list.hidden) { abrir(); return; }
      if (e.key === "ArrowDown") mover(1);
      else if (e.key === "ArrowUp") mover(-1);
      else {
        const act = list.querySelector("li.activo");
        if (act) elegir(Number(act.dataset.i));
      }
    } else if (e.key === "Escape") {
      cerrar();
    } else if (e.key.length === 1) {
      // Tipear una letra salta a la primera opción que empieza con ella, como
      // hace el select nativo. En la lista de 42 semanas es lo que la hace usable.
      const i = opciones().findIndex((o) =>
        o.textContent.trim().toLowerCase().startsWith(e.key.toLowerCase()));
      if (i >= 0) { if (list.hidden) abrir(); mover(i - (opciones().findIndex((o) => o.selected))); }
    }
  });

  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) cerrar();
  });

  // Cuando algo cambia el valor por código —vaciar todo, cargar el ejemplo— el
  // botón tiene que reflejarlo. Por eso se escucha el mismo `change`.
  sel.addEventListener("change", pintarBoton);
  pintarBoton();
  return { sync: pintarBoton };
}

/* ---------------- perfil ---------------- */

const semanasSel = $("semanas");
for (let w = 1; w <= 42; w++) {
  const o = document.createElement("option");
  o.value = String(w);
  semanasSel.appendChild(o);
}
// Generadas por script, así que `data-i18n` no las alcanza: se traducen acá
// y de nuevo en cada cambio de idioma (ver `onLangChange`).
function actualizarTextoSemanas() {
  [...semanasSel.options].forEach((o) => {
    o.textContent = o.value ? t("semana_n", { n: o.value }) : t("semana_placeholder");
  });
}
actualizarTextoSemanas();

// Los cuatro desplegables de la pantalla. `semanas` va en dos columnas porque
// son 43 opciones y a una columna obliga a scrollear.
const SELECTS = {
  sexo: enhanceSelect($("sexo")),
  renal: enhanceSelect($("renal")),
  hepatica: enhanceSelect($("hepatica")),
  semanas: enhanceSelect(semanasSel, { compacto: true }),
};
// `disabled` no emite ningún evento, así que el botón no se entera solo.
const setSemanasDisabled = (v) => { semanasSel.disabled = v; SELECTS.semanas.sync(); };

$("sexo").addEventListener("change", (e) => {
  // Embarazo y lactancia sólo se ofrecen con sexo femenino declarado. Si se
  // cambia a masculino se limpian, para no mandar un perfil incoherente.
  const f = e.target.value === "F";
  $("gestacion").hidden = !f;
  if (!f) {
    $("embarazo").checked = false;
    $("lactancia").checked = false;
    semanasSel.value = "";
    setSemanasDisabled(true);
  }
  invalidateResults();
  syncButtons();
});

$("embarazo").addEventListener("change", (e) => {
  setSemanasDisabled(!e.target.checked);
  if (!e.target.checked) semanasSel.value = "";
  invalidateResults();
  syncButtons();
});

$("edad").addEventListener("input", () => {
  const n = Number($("edad").value);
  $("aviso-edad").hidden = !($("edad").value && n >= 65);
});

["edad", "lactancia", "renal", "hepatica", "semanas"].forEach((id) =>
  $(id).addEventListener("change", () => { invalidateResults(); syncButtons(); }));

function perfil() {
  return {
    sexo: $("sexo").value || null,
    edad: $("edad").value ? Number($("edad").value) : null,
    embarazo: $("embarazo").checked,
    semanas_gestacion: semanasSel.value ? Number(semanasSel.value) : null,
    lactancia: $("lactancia").checked,
    funcion_renal: $("renal").value || null,
    funcion_hepatica: $("hepatica").value || null,
    alergias: alergias.map((a) => a.name),
    patologias_mesh: [],
    patologias_icd10: patologias.map((p) => p.code),
  };
}

// La edad SÍ cuenta: desde que existen los criterios de prescripción en el
// anciano, un perfil con sólo la edad ya genera alertas. Dejarla afuera hacía
// que la interfaz no llamara nunca a /contraindications para un paciente de 80
// sin ninguna otra condición cargada.
const hayPerfil = () => {
  const p = perfil();
  return Boolean(p.embarazo || p.lactancia || p.funcion_renal ||
                 p.funcion_hepatica || p.alergias.length ||
                 p.patologias_icd10.length || p.edad !== null);
};

/* ---------------- estado ---------------- */

// `error` NO es lo mismo que `null`. Si una consulta falla y se guarda como
// null, la pantalla dice "completá el perfil" o "agregá medicamentos": presenta
// una caída del servidor como si faltaran datos. En una herramienta clínica ése
// es el peor modo de fallo, porque el vacío tranquiliza.
let ultimo = { inter: null, contra: null, interError: null, contraError: null };

function invalidateResults() {
  const box = $("results");
  ultimo = { inter: null, contra: null, interError: null, contraError: null };
  if (!box.hidden) {
    box.hidden = true;
    $("results-body").innerHTML = "";
    $("filtros").hidden = true;
    $("sources").textContent = "";
  }
}

function syncButtons() {
  // Con un solo medicamento no hay pares que cruzar, pero sí puede haber
  // alertas contra el paciente. Por eso alcanza con uno si hay perfil.
  $("check").disabled = selected.length < 2 && !(selected.length === 1 && hayPerfil());
  $("clear").hidden = selected.length === 0 && alergias.length === 0 &&
                      patologias.length === 0 && !hayPerfil();
  const n = selected.length;
  $("cnt-meds").textContent = n ? `${n} ${n === 1 ? t("n_medicamento") : t("n_medicamentos")}` : "";
  $("cnt-meds").hidden = !n;

  const pares = n * (n - 1) / 2;
  const r = $("resumen-cruce");
  r.hidden = n < 1;
  if (n >= 2) {
    r.innerHTML = t("resumen_cruce_multi", {
      pares, palabra: pares === 1 ? t("n_combinacion") : t("n_combinaciones"),
    });
  } else if (n === 1) {
    r.innerHTML = t("resumen_cruce_uno");
  }

  const campos = [
    $("sexo").value, $("edad").value, $("renal").value, $("hepatica").value,
    $("embarazo").checked ? "1" : "", $("lactancia").checked ? "1" : "",
  ].filter(Boolean).length + alergias.length + patologias.length;
  $("cnt-perfil").textContent = campos ? `${campos} ${campos === 1 ? t("n_dato") : t("n_datos")}` : "";
  $("cnt-perfil").hidden = !campos;
}

// Nombre a mostrar de un resultado de búsqueda de fármaco: el mismo criterio
// que `mostrar()`, pero antes de que el ítem tenga su `name` mapeado en
// `NOMBRE_ES` (acá se usa directamente el `name_es` que trae la respuesta).
const nombreFarmaco = (r) => (LANG === "es" ? (r.name_es || r.name) : r.name);
const aliasFarmaco = (r) => (LANG === "es" ? (r.name_es ? r.name : null) : (r.name_es || null));
const nombrePatologia = (r) => (LANG === "es" ? condEs(r.name) : r.name);

const meds = wireSearch({
  input: $("q"), list: $("suggestions"), target: selected, chips: $("chips"),
  onChange: syncButtons, fetchFn: buscarFarmacos,
  renderItem: (r) => `<span class="nombre">${escapeHtml(nombreFarmaco(r))}${
    aliasFarmaco(r) ? `<span class="alias-en"> · ${escapeHtml(aliasFarmaco(r))}</span>` : ""}</span>${
    r.rxcui ? `<span class="rxcui">RxCUI ${r.rxcui}</span>` : ""}`,
  renderChip: (s) => escapeHtml(nombreFarmaco(s)),
});
const alerg = wireSearch({
  input: $("qa"), list: $("suggestions-alergias"), target: alergias,
  chips: $("chips-alergias"), onChange: syncButtons, fetchFn: buscarFarmacos,
  renderItem: (r) => `<span class="nombre">${escapeHtml(nombreFarmaco(r))}</span>`,
  renderChip: (s) => escapeHtml(nombreFarmaco(s)),
});
const patol = wireSearch({
  input: $("qp"), list: $("suggestions-patologias"), target: patologias,
  chips: $("chips-patologias"), onChange: syncButtons, fetchFn: buscarPatologias,
  // Se muestra cuántas alertas cuelgan del código: es la única forma de que el
  // médico sepa, antes de elegirlo, si ese código va a evaluar algo. Un
  // descendiente (p.ej. N18.5) no dispara alerta propia, dispara la de su
  // anclaje (N18): se lo indica sutil, en los dos idiomas (`evalua_como`).
  renderItem: (r) => `<span class="code">${escapeHtml(r.code)}</span>
    <span class="nombre">${escapeHtml(nombrePatologia(r))}</span>
    <span class="alertas">${r.alertas} ${r.alertas === 1 ? t("alerta_1") : t("alerta_n")}</span>${
    r.anchor_code && r.anchor_code !== r.code
      ? `<span class="resuelve-como">${escapeHtml(t("evalua_como", { code: r.anchor_code }))}</span>`
      : ""}`,
  renderChip: (s) => `<span class="code">${escapeHtml(s.code)}</span> ${escapeHtml(nombrePatologia(s))}`,
});

$("clear").addEventListener("click", () => {
  selected.length = 0;
  alergias.length = 0;
  patologias.length = 0;
  // También el texto tipeado: dejarlo quedaba un "penicillin" suelto en el
  // campo después de vaciar, como si siguiera cargado.
  ["q", "qa", "qp"].forEach((id) => { $(id).value = ""; });
  ["suggestions", "suggestions-alergias", "suggestions-patologias"]
    .forEach((id) => { $(id).hidden = true; });
  ["sexo", "edad", "renal", "hepatica"].forEach((id) => {
    $(id).value = "";
    SELECTS[id]?.sync();
  });
  $("embarazo").checked = false;
  $("lactancia").checked = false;
  semanasSel.value = "";
  setSemanasDisabled(true);
  $("gestacion").hidden = true;
  $("aviso-edad").hidden = true;
  invalidateResults();
  meds.render(); alerg.render(); patol.render();
});

// "¿Qué evalúa?" y "Los datos" son dos paneles bajo la cabecera; abrir uno
// cierra el otro, para no apilar dos pantallas de texto sobre el formulario.
function abrirPanel(id, abrir) {
  const btn = { ayuda: $("btn-ayuda"), datos: $("btn-datos") };
  for (const k of Object.keys(btn)) {
    const on = k === id ? abrir : false;
    $(k).hidden = !on;
    btn[k].setAttribute("aria-expanded", String(on));
  }
  if (id === "datos" && abrir) cargarDatos();
}

$("btn-ayuda").addEventListener("click", () => abrirPanel("ayuda", $("ayuda").hidden));
$("btn-datos").addEventListener("click", () => abrirPanel("datos", $("datos").hidden));
$("btn-ver-datos").addEventListener("click", () => {
  abrirPanel("datos", true);
  $("datos").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("btn-cerrar-datos").addEventListener("click", () => {
  abrirPanel("datos", false);
  $("btn-datos").focus();
});

/* ---------------- sección "Los datos" ----------------
   Todo número y toda fecha salen de GET /data/summary (pública, sin key).
   Se pide una sola vez: la base es inmutable mientras corre el servicio. */

let DATOS = null;
let datosPedidos = false;

async function cargarDatos() {
  if (datosPedidos) return;
  datosPedidos = true;
  try {
    const r = await fetch("/data/summary", { headers: headers() });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    DATOS = await r.json();
    renderDatos();
  } catch (err) {
    datosPedidos = false;   // se puede reintentar cerrando y abriendo
    $("datos-stats").innerHTML =
      `<p class="datos-cargando">${escapeHtml(t("datos_error", { detalle: err.message }))}</p>`;
  }
}

const fmtNum = (n) => new Intl.NumberFormat(t("locale")).format(n ?? 0);
const fmtPct = (p) => new Intl.NumberFormat(t("locale"),
  { style: "percent", maximumFractionDigits: 1 }).format((p ?? 0) / 100);
// `null` NO se reemplaza por otra fecha: se dice que no hay.
const fmtFecha = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d) ? null : d.toLocaleDateString(t("locale"),
    { day: "numeric", month: "long", year: "numeric" });
};

// Qué fuente, con qué licencia y dónde. Las cantidades y fechas se completan
// con la respuesta del endpoint.
const FUENTES_DATOS = [
  { k: "ddinter", nombre: "DDInter 2.0", licencia: () => "CC BY-NC-SA 4.0",
    url: "https://ddinter2.scbdd.com/",
    cant: (d) => t("f_cant_ddinter", { n: fmtNum(d.interactions.by_source.ddinter) }) },
  { k: "aemps", nombre: "AEMPS", licencia: () => t("lic_aemps"),
    url: "https://www.aemps.gob.es/",
    cant: (d) => t("f_cant_aemps", {
      ix: fmtNum(d.interactions.by_source.aemps), clases: fmtNum(d.duplicity.classes),
      geri: fmtNum(d.geriatric_criteria) }) },
  { k: "openfda", nombre: "openFDA", licencia: () => t("lic_openfda"),
    url: "https://open.fda.gov/",
    cant: (d) => t("f_cant_openfda", { n: fmtNum(d.interactions.by_source.openfda) }) },
  { k: "medrt", nombre: "MED-RT", licencia: () => t("lic_nlm"),
    url: "https://www.nlm.nih.gov/research/umls/sourcereleasedocs/current/MED-RT/",
    cant: (d) => t("f_cant_medrt", { n: fmtNum(d.condition_alerts.total) }) },
  { k: "rxnorm", nombre: "RxNorm", licencia: () => t("lic_nlm"),
    url: "https://www.nlm.nih.gov/research/umls/rxnorm/",
    cant: (d) => t("f_cant_rxnorm", { n: fmtNum(d.drugs.with_rxcui) }) },
  { k: "dnma", nombre: () => t("f_nombre_dnma"), licencia: () => t("lic_dnma"),
    url: "https://www.gub.uy/ministerio-salud-publica/",
    cant: (d) => t("f_cant_dnma", { mapped: fmtNum(d.dnma.mapped), total: fmtNum(d.dnma.substances) }) },
  { k: "icd10_bridge", aporta: "puente", nombre: () => t("f_nombre_puente"),
    licencia: () => t("lic_puente"), url: null,
    cant: (d) => t("f_cant_puente", {
      codigos: fmtNum(d.conditions.icd10), links: fmtNum(d.conditions.icd10_links) }) },
];

function renderDatos() {
  const d = DATOS;
  if (!d) return;
  const ix = d.interactions;
  const nFuentes = Object.values(ix.by_source).filter((n) => n > 0).length;
  const tiles = [
    { n: ix.distinct_pairs, l: t("stat_pares_l"),
      s: t("stat_pares_s", { total: fmtNum(ix.total), n: nFuentes }), hero: true },
    { n: d.drugs.total, l: t("stat_farmacos_l"),
      s: t("stat_farmacos_s", { pct: fmtPct(d.drugs.spanish_name_pct) }) },
    { n: d.duplicity.classes, l: t("stat_dup_l"),
      s: t("stat_dup_s", { miembros: fmtNum(d.duplicity.class_memberships),
                           exc: fmtNum(d.duplicity.curated_exceptions) }) },
    { n: d.geriatric_criteria, l: t("stat_geri_l"), s: t("stat_geri_s") },
    { n: d.condition_alerts.total, l: t("stat_pat_l"),
      s: t("stat_pat_s", { ci: fmtNum(d.condition_alerts.contraindications),
                           pre: fmtNum(d.condition_alerts.precautions),
                           cie: fmtNum(d.conditions.icd10) }) },
  ];
  $("datos-stats").innerHTML = tiles.map((x) => `
    <div class="stat${x.hero ? " stat-hero" : ""}">
      <span class="stat-n">${fmtNum(x.n)}</span>
      <span class="stat-l">${escapeHtml(x.l)}</span>
      <span class="stat-s">${escapeHtml(x.s)}</span>
    </div>`).join("");

  // Distribución por gravedad: barra apilada con los colores de gravedad de
  // toda la app, y leyenda con número y porcentaje (el color nunca va solo).
  const orden = ["major", "moderate", "minor", "unknown"];
  const total = orden.reduce((a, k) => a + (ix.by_severity[k] || 0), 0);
  if (total) {
    const pct = (k) => (100 * (ix.by_severity[k] || 0)) / total;
    $("datos-sev").innerHTML = `
      <h3 class="datos-h3">${escapeHtml(t("sev_dist_h"))}</h3>
      <div class="sev-bar" role="img" aria-label="${escapeAttr(t("sev_dist_aria"))}">
        ${orden.filter((k) => ix.by_severity[k]).map((k) => `
          <span class="seg ${k}" style="flex-grow:${pct(k)}"
                title="${escapeAttr(`${SEV[k].label}: ${fmtNum(ix.by_severity[k])} (${fmtPct(pct(k))})`)}"></span>`).join("")}
      </div>
      <ul class="sev-leyenda">
        ${orden.map((k) => `<li><span class="dot ${k}"></span>
          <strong>${escapeHtml(SEV[k].label)}</strong>
          <span class="num">${fmtNum(ix.by_severity[k] || 0)}</span>
          <span class="pct">${fmtPct(pct(k))}</span></li>`).join("")}
      </ul>`;
    $("datos-sev").hidden = false;
  }

  $("datos-fuentes").innerHTML = FUENTES_DATOS.map((f) => {
    const src = d.sources[f.k] || {};
    const fecha = fmtFecha(src.updated_at);
    const nombre = typeof f.nombre === "function" ? f.nombre() : f.nombre;
    const version = f.k === "ddinter" && src.release
      ? `<span class="fuente-version">${escapeHtml(t("datos_version", { v: src.release }))}</span>` : "";
    return `
      <article class="fuente-card">
        <header>
          <h4>${escapeHtml(nombre)}</h4>${version}
        </header>
        <p class="fuente-aporta">${escapeHtml(t(`f_aporta_${f.aporta || f.k}`))}</p>
        <p class="fuente-cant">${escapeHtml(f.cant(d))}</p>
        <dl>
          <dt>${escapeHtml(t("datos_licencia"))}</dt><dd>${escapeHtml(f.licencia())}</dd>
        </dl>
        <div class="fuente-pie">
          <span class="fuente-fecha${fecha ? "" : " sin-fecha"}">${escapeHtml(
            fecha ? t("datos_actualizado", { fecha }) : t("datos_sin_fecha"))}</span>
          ${f.url ? `<a href="${escapeAttr(f.url)}" target="_blank" rel="noopener">${escapeHtml(t("datos_sitio"))} ↗</a>` : ""}
        </div>
      </article>`;
  }).join("");

  const b = d.sources.build || {};
  const fb = fmtFecha(b.timestamp);
  $("datos-build").textContent = fb && b.sha ? t("datos_build", { fecha: fb, sha: b.sha }) : "";
}

// Link directo a la sección (para difundir): /#datos la abre al cargar.
if (location.hash === "#datos") abrirPanel("datos", true);

// Busca por nombre en castellano (mismo endpoint que el autocompletado) y se
// queda con el match exacto, en los dos idiomas: `nombre` está en castellano,
// pero `r.name` es el canónico (a veces inglés) y sólo `r.name_es` puede
// tener la grafía local.
async function resolverFarmaco(nombre) {
  const res = await buscarFarmacos(nombre);
  return res.find((r) =>
    r.name.toLowerCase() === nombre ||
    (r.name_es || "").toLowerCase() === nombre) || res[0] || null;
}

$("btn-ejemplo").addEventListener("click", async () => {
  $("clear").click();   // mismo estado que "Vaciar todo": sin perfil ni caso anterior
  for (const nombre of EJEMPLO.drugs) {
    try {
      const exacto = await resolverFarmaco(nombre);
      if (exacto) selected.push(exacto);
    } catch { /* si falla uno, se cargan los demás */ }
  }
  invalidateResults();
  meds.render();
  syncButtons();
  if (!selected.length) toast(t("toast_ejemplo_error"));
  else $("check").focus();
});

/* Ejemplo con paciente: un caso que dispara a la vez las cuatro familias de
   alertas contra el paciente y la receta. Verificado contra la API
   (2026-09-25, base con build adf0337):
     - contraindicación: metformina con insuficiencia renal (MED-RT, vía N18.5);
     - alergia: amoxicilina declarada y recetada (coincidencia exacta);
     - criterios en el anciano (AEMPS): diazepam, lorazepam e ibuprofeno;
     - duplicidad: diazepam + lorazepam, clase N05BA (AEMPS);
     - interacciones DDInter: metformina + ibuprofeno moderada, y nueve pares
       "revisar".
   La función renal va en "grave" por coherencia con un estadio 5; hoy no
   agrega alertas propias (la contraindicación ya sale de la patología). */
const EJEMPLO_PACIENTE = {
  drugs: ["metformina", "diazepam", "lorazepam", "amoxicilina", "ibuprofeno"],
  alergias: ["amoxicilina"],
  // Desde `icd10_descendant` (scripts/load_icd10_descendientes.py) el
  // autocompletado ya ofrece N18.5, no sólo sus anclajes (N18, N18.9). Se
  // busca igual por `buscarPatologias` y se usa lo que devuelva —el `código +
  // nombre` oficial CIE-10 (CMS)—; el literal de acá es sólo el respaldo si
  // la búsqueda llegara a fallar.
  patologia: { code: "N18.5", name: "Chronic kidney disease, stage 5" },
  perfil: { sexo: "F", edad: 78, renal: "grave" },
};

$("btn-ejemplo-paciente").addEventListener("click", async () => {
  $("clear").click();   // mismo estado que "Vaciar todo": nada del caso anterior

  const cargar = async (nombres, destino) => {
    for (const nombre of nombres) {
      try {
        const r = await resolverFarmaco(nombre);
        if (r) destino.push(r);
      } catch { /* si falla uno, se cargan los demás */ }
    }
  };
  await cargar(EJEMPLO_PACIENTE.drugs, selected);
  await cargar(EJEMPLO_PACIENTE.alergias, alergias);

  const p = EJEMPLO_PACIENTE.patologia;
  try {
    const res = await buscarPatologias(p.code);
    patologias.push(res.find((r) => r.code === p.code) || { id: p.code, ...p });
  } catch {
    patologias.push({ id: p.code, ...p });
  }

  const pf = EJEMPLO_PACIENTE.perfil;
  $("sexo").value = pf.sexo;
  $("sexo").dispatchEvent(new Event("change"));   // muestra embarazo/lactancia
  SELECTS.sexo.sync();
  $("edad").value = pf.edad;
  $("aviso-edad").hidden = false;
  $("renal").value = pf.renal;
  SELECTS.renal.sync();

  invalidateResults();
  meds.render(); alerg.render(); patol.render();
  syncButtons();
  if (!selected.length) { toast(t("toast_ejemplo_paciente_error")); return; }
  // Se consulta de una: el punto del ejemplo es ver las alertas, no el formulario.
  if (!$("check").disabled) {
    await consultar();
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

/* ---------------- consulta ---------------- */

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !$("check").disabled) {
    e.preventDefault();
    $("check").click();
  }
});

async function consultar() {
  const btn = $("check");
  btn.disabled = true;
  btn.textContent = t("btn_consultando");
  const drugs = selected.map((s) => s.name);
  let inter = null, contra = null, interError = null, contraError = null;

  try {
    const calls = [];
    if (drugs.length >= 2) {
      calls.push(fetch("/interactions", {
        method: "POST", headers: headers(), body: JSON.stringify({ drugs }),
      }).then(async (r) => {
        if (r.ok) inter = await r.json();
        else { interError = descripcionError(r); handleHttpError(r); }
      }));
    }
    if (hayPerfil()) {
      calls.push(fetch("/contraindications", {
        method: "POST", headers: headers(),
        body: JSON.stringify({ drugs, profile: perfil() }),
      }).then(async (r) => {
        if (r.ok) contra = await r.json();
        else { contraError = descripcionError(r); handleHttpError(r); }
      }));
    }
    await Promise.all(calls);
  } catch {
    toast(t("toast_error_servicio"));
    interError = contraError = t("error_sin_contacto");
  }
  btn.textContent = t("btn_consultar");
  syncButtons();
  // Fuera del try: un error al pintar no puede disfrazarse de error de red.
  ultimo = { inter, contra, interError, contraError };
  construirFiltros(inter, contra);
  render();
}
$("check").addEventListener("click", consultar);

/* Los hallazgos contra el paciente no traen `severity`, pero sí tienen una:
   una contraindicación pesa como una interacción grave y una precaución como
   una moderada. Sin esto el filtro de gravedad sólo cubría una de las dos
   columnas, y filtrar por "Grave" dejaba tarjetas ámbar a la vista. */
const SEV_PACIENTE = {
  alergia: "major",
  contraindication: "major",
  precaution: "moderate",
  // El criterio geriátrico condicionado no afirma nada todavía: es moderado.
  geriatrica: (g) => (g.condicionada ? "moderate" : "major"),
};
const sevPaciente = (tipo, item) => {
  const v = SEV_PACIENTE[tipo];
  return typeof v === "function" ? v(item) : v;
};

// Una duplicidad sin severidad reconocida no es "sin graduar" como una
// interacción: cae en moderada, igual que la tarjeta la pinta.
const sevDuplicidad = (d) => (SEV[d.severity] ? d.severity : "moderate");

/* ---------------- filtros ----------------
   Se arman sobre lo que efectivamente se encontró: ofrecer un filtro "Leve"
   cuando no hay ninguna leve es prometer algo que no está. */

const filtro = {
  sev: new Set(), fuente: new Set(), conTexto: false, sinInferidas: false, texto: "",
};

function construirFiltros(inter, contra) {
  const hallazgos = [
    ...(inter?.interactions || []),
    ...(inter?.duplicities || []).map((d) => ({ ...d, severity: sevDuplicidad(d) })),
  ];
  // Las dos columnas alimentan los mismos contadores: un filtro que dice
  // "Grave 3" y deja cuatro tarjetas rojas en pantalla no se entiende.
  const delPaciente = [
    ...(contra?.allergies || []).filter((a) => a.match === "exact")
      .map((a) => ({ severity: "major", source: "perfil" })),
    ...(contra?.contraindications || []).map((c) => ({ severity: "major", source: c.source })),
    ...(contra?.precautions || []).map((c) => ({ severity: "moderate", source: c.source })),
    ...(contra?.geriatric || []).map((g) => ({
      severity: sevPaciente("geriatrica", g), source: g.source })),
  ];
  filtro.sev.clear(); filtro.fuente.clear();
  filtro.conTexto = false; filtro.sinInferidas = false; filtro.texto = "";
  $("f-con-texto").checked = false;
  $("f-sin-inferidas").checked = false;
  $("f-texto").value = "";

  const porSev = {}, porFuente = {};
  [...hallazgos, ...delPaciente].forEach((i) => {
    const s = SEV[i.severity] ? i.severity : "unknown";
    porSev[s] = (porSev[s] || 0) + 1;
    porFuente[i.source] = (porFuente[i.source] || 0) + 1;
  });

  $("f-sev").innerHTML = Object.keys(SEV)
    .filter((s) => porSev[s])
    .map((s) => `<button type="button" class="pill" aria-pressed="false" data-sev="${s}">
       <span class="dot ${s}"></span>${SEV[s].label} <span class="n">${porSev[s]}</span>
     </button>`).join("");
  $("f-sev-grupo").hidden = !$("f-sev").innerHTML;

  $("f-fuente").innerHTML = Object.keys(porFuente).sort()
    .map((f) => `<button type="button" class="pill" aria-pressed="false" data-fuente="${f}"
       title="${escapeAttr(FUENTE[f] || f)}">${FUENTE_CORTA[f] || f}
       <span class="n">${porFuente[f]}</span></button>`).join("");
  $("f-fuente-grupo").hidden = !$("f-fuente").innerHTML;

  $("f-sev").querySelectorAll("[data-sev]").forEach((b) =>
    b.addEventListener("click", () => toggle(filtro.sev, b.dataset.sev, b)));
  $("f-fuente").querySelectorAll("[data-fuente]").forEach((b) =>
    b.addEventListener("click", () => toggle(filtro.fuente, b.dataset.fuente, b)));

  const hayAlgo = hallazgos.length || (contra && (
    (contra.contraindications || []).length + (contra.precautions || []).length +
    (contra.geriatric || []).length + (contra.allergies || []).length));
  $("filtros").hidden = !hayAlgo;
}

function toggle(set, valor, btn) {
  if (set.has(valor)) set.delete(valor); else set.add(valor);
  btn.classList.toggle("on", set.has(valor));
  btn.setAttribute("aria-pressed", String(set.has(valor)));
  render();
}

["f-con-texto", "f-sin-inferidas"].forEach((id) =>
  $(id).addEventListener("change", (e) => {
    filtro[id === "f-con-texto" ? "conTexto" : "sinInferidas"] = e.target.checked;
    e.target.closest(".pill").classList.toggle("on", e.target.checked);
    render();
  }));

let tTexto = null;
$("f-texto").addEventListener("input", (e) => {
  clearTimeout(tTexto);
  tTexto = setTimeout(() => { filtro.texto = e.target.value.trim().toLowerCase(); render(); }, 160);
});

$("f-reset").addEventListener("click", () => {
  filtro.sev.clear(); filtro.fuente.clear();
  filtro.conTexto = filtro.sinInferidas = false; filtro.texto = "";
  $("f-con-texto").checked = $("f-sin-inferidas").checked = false;
  $("f-texto").value = "";
  document.querySelectorAll(".pill.on").forEach((p) => {
    p.classList.remove("on");
    if (p.hasAttribute("aria-pressed")) p.setAttribute("aria-pressed", "false");
  });
  render();
});

const hayFiltro = () => filtro.sev.size || filtro.fuente.size ||
                        filtro.conTexto || filtro.sinInferidas || filtro.texto;

function pasaFiltro(i) {
  const s = SEV[i.severity] ? i.severity : "unknown";
  if (filtro.sev.size && !filtro.sev.has(s)) return false;
  if (filtro.fuente.size && !filtro.fuente.has(i.source)) return false;
  if (filtro.conTexto && !i.description && !i.management) return false;
  if (filtro.sinInferidas && i.uncertain) return false;
  if (filtro.texto) {
    const blob = [i.drug_a, i.drug_b, i.description, i.management]
      .filter(Boolean).join(" ").toLowerCase();
    if (!blob.includes(filtro.texto)) return false;
  }
  return true;
}

function pasaFiltroPaciente(campos, sev, fuente) {
  if (filtro.sev.size && !filtro.sev.has(sev)) return false;
  if (filtro.fuente.size && !filtro.fuente.has(fuente)) return false;
  // "Sólo con explicación" y "ocultar inferidas" son propiedades de una
  // interacción: no se les aplican, porque acá siempre hay texto y nada se
  // infiere de prosa libre.
  if (!filtro.texto) return true;
  return campos.filter(Boolean).join(" ").toLowerCase().includes(filtro.texto);
}

/* ---------------- pintado ---------------- */

function render() {
  const { inter, contra, interError, contraError } = ultimo;
  const box = $("results");
  let html = '<div class="cols">';
  let ocultos = 0;

  /* --- columna 1: medicamento <-> medicamento --- */
  html += `<div class="col"><p class="col-title">${t("col_title_inter")}</p>`;
  if (inter) {
    const todos = (inter.interactions || []).slice()
      .sort((a, b) => (SEV[a.severity]?.rank ?? 9) - (SEV[b.severity]?.rank ?? 9));
    const found = todos.filter(pasaFiltro);
    ocultos += todos.length - found.length;
    const pares = selected.length * (selected.length - 1) / 2;
    html += found.map(cardInteraccion).join("");
    const dupsTodos = inter.duplicities || [];
    const dups = dupsTodos.filter((d) =>
      pasaFiltroPaciente([d.class_desc, ...(d.substances || [])], sevDuplicidad(d), d.source));
    ocultos += dupsTodos.length - dups.length;
    html += dups.map((d) => cardDuplicidad(d, false)).join("");
    // Lo suprimido se muestra plegado: se evaluó y se decidió no alertar.
    const sup = inter.duplicities_suppressed || [];
    if (sup.length && !hayFiltro()) {
      html += `<details class="suprimidas"><summary>${sup.length}
        ${sup.length === 1 ? t("sup_duplicidad_1") : t("sup_duplicidad_n")}
        ${t("sup_por_excepcion")}</summary>${sup.map((d) => cardDuplicidad(d, true)).join("")}</details>`;
    }
    if (!hayFiltro()) {
      (inter.duplicity_not_evaluated || []).forEach((n) => {
        html += `<div class="empty-state"><strong>${escapeHtml(n)}</strong> ${t("empty_no_identificado_dup_pre")}</div>`;
      });
      (inter.duplicity_warnings || []).forEach((w) => {
        html += `<div class="aviso-perfil">${escapeHtml(w)}</div>`;
      });
    }
    // "Ningún hallazgo coincide" cubre ambos tipos: sólo aparece si no queda
    // ni una interacción ni una duplicidad visible, y sólo cuando había algo
    // que los filtros pudieran haber escondido.
    if (!found.length && !dups.length && (todos.length || dupsTodos.length)) {
      html += `<div class="empty-state">${t("empty_sin_filtros")}</div>`;
    }
    // Esto habla de interacciones, no de duplicidad: que una combinación no
    // tenga interacción documentada no contradice que sí tenga una tarjeta de
    // duplicidad arriba, así que no se gatea con `dups.length`.
    const sin = pares - todos.length;
    if (sin > 0 && !hayFiltro()) {
      // Nunca "es seguro": decimos que no encontramos evidencia.
      html += `<div class="empty-state"><strong>${t("empty_sin_combinacion", {
        sin, palabra: sin === 1 ? t("n_combinacion") : t("n_combinaciones"),
      })}</strong> ${t("empty_sin_combinacion_nota")}</div>`;
    }
  } else if (interError) {
    html += cardError(t("error_titulo_inter"), interError);
  } else {
    html += `<div class="empty-state">${t("empty_agregar_meds")}</div>`;
  }
  html += "</div>";

  /* --- columna 2: medicamento <-> paciente --- */
  html += `<div class="col"><p class="col-title">${t("col_title_contra")}</p>`;
  if (contra) {
    (contra.profile_warnings || []).forEach((w) => {
      html += `<div class="aviso-perfil">${escapeHtml(w)}</div>`;
    });
    const al = (contra.allergies || []).filter((a) => a.match === "exact")
      .filter((a) => pasaFiltroPaciente([a.drug, a.declared_as], "major", "perfil"));
    const noId = (contra.allergies || []).filter((a) => a.match === "unresolved");
    const ci = (contra.contraindications || [])
      .filter((c) => pasaFiltroPaciente([c.drug, condLabel(c.condition)], "major", c.source));
    const pre = (contra.precautions || [])
      .filter((c) => pasaFiltroPaciente([c.drug, condLabel(c.condition)], "moderate", c.source));
    const geri = (contra.geriatric || []).filter((g) =>
      pasaFiltroPaciente([g.drug, g.situacion, g.recomendacion],
                         sevPaciente("geriatrica", g), g.source));

    ocultos += (contra.allergies || []).filter((a) => a.match === "exact").length - al.length;
    ocultos += (contra.contraindications || []).length - ci.length;
    ocultos += (contra.precautions || []).length - pre.length;
    ocultos += (contra.geriatric || []).length - geri.length;

    html += al.map(cardAlergia).join("");
    html += ci.map((c) => cardPaciente(c, "major")).join("");
    html += pre.map((c) => cardPaciente(c, "moderate")).join("");
    html += geri.map(cardGeriatrica).join("");

    // Lo que no se pudo evaluar se dice, no se omite.
    if (!hayFiltro()) {
      noId.forEach((a) => {
        html += `<div class="empty-state">${t("empty_no_identificado_alergia_pre")}
          <strong>${escapeHtml(a.declared_as)}</strong> ${t("empty_no_identificado_alergia_post")}</div>`;
      });
      (contra.not_evaluated || []).forEach((n) => {
        html += `<div class="empty-state"><strong>${escapeHtml(n.drug || n.icd10)}</strong>
          ${t("empty_no_evaluado", { motivo: escapeHtml(n.reason) })}</div>`;
      });
    }

    const total = al.length + ci.length + pre.length + geri.length;
    if (total === 0 && !noId.length) {
      html += hayFiltro()
        ? `<div class="empty-state">${t("empty_sin_filtros")}</div>`
        : `<div class="empty-state"><strong>${t("empty_sin_alertas_perfil_t")}</strong>
             ${t("empty_sin_alertas_perfil_d")}</div>`;
    }
  } else if (contraError) {
    html += cardError(t("error_titulo_contra"), contraError);
  } else {
    html += `<div class="empty-state">${t("empty_completar_perfil")}</div>`;
  }
  html += "</div></div>";

  $("results-body").innerHTML = html;
  box.hidden = false;

  $("f-reset").hidden = !hayFiltro();
  $("filtro-estado").hidden = !ocultos;
  $("filtro-estado").textContent = ocultos
    ? t("filtro_estado", { n: ocultos, palabra: ocultos === 1 ? t("n_hallazgo_oculto") : t("n_hallazgos_ocultos") })
    : "";

  const cov = (inter && inter.coverage_summary) || {};
  const partes = Object.entries(cov).filter(([k, n]) => n > 0 && k !== "unknown")
    .map(([k, n]) => `${n} ${t("cov_de")} ${FUENTE[k] || k}`);
  if (contra && ((contra.contraindications || []).length || (contra.precautions || []).length)) {
    partes.push(FUENTE.medrt);
  }
  $("sources").textContent = partes.length ? t("fuentes_consultadas", { lista: partes.join(" · ") }) : "";
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function descripcionError(r) {
  if (r.status === 401) return t("err_desc_401");
  if (r.status === 429) return t("err_desc_429");
  if (r.status === 503) return t("err_desc_503");
  return t("err_desc_generico", { status: r.status });
}

/* Una consulta que falló NO se pinta como un resultado vacío. Es la diferencia
   entre "no hay alertas" y "no sabemos si hay alertas", y en una receta esa
   diferencia es todo. */
function cardError(titulo, detalle) {
  return `
    <div class="error-state">
      <strong>${escapeHtml(titulo)}</strong>
      <p>${escapeHtml(detalle)} ${t("error_detalle_post")}</p>
      <button type="button" class="btn-ghost" onclick="document.getElementById('check').click()">
        ${t("btn_reintentar")}</button>
    </div>`;
}

function cardInteraccion(i) {
  const sev = SEV[i.severity] ? i.severity : "unknown";
  // El modo de match sólo se muestra cuando la regla fue de CLASE: es menos
  // específica que una de molécula y el médico tiene derecho a saberlo.
  const porClase = (i.text_match || "").includes("clase");
  // Texto clínico libre: se muestra tal cual salió de la fuente, con su
  // idioma real en `lang` y, si no coincide con la interfaz, un aviso chico.
  const idiomaTexto = FUENTE_TEXTO_IDIOMA[i.source];
  return `
    <article class="finding ${sev}">
      <div class="finding-head">
        <span class="pair">${escapeHtml(mostrar(i.drug_a))} + ${escapeHtml(mostrar(i.drug_b))}</span>
        <span class="badge ${sev}">${SEV[sev].label}</span>
        ${i.uncertain ? `<span class="tag-uncertain">${t("tag_inferida")}</span>` : ""}
        ${porClase ? `<span class="tag-clase">${t("tag_clase")}</span>` : ""}
      </div>
      ${i.description
        ? `<p class="evidence"${idiomaTexto ? ` lang="${idiomaTexto}"` : ""}>${
             escapeHtml(i.description)}</p>${idiomaTexto ? notaFuenteIdioma(idiomaTexto) : ""}`
        : `<p class="evidence sin-texto">${sev === "unknown"
             ? t("evidence_sin_gravedad")
             : t("evidence_sin_descripcion")}</p>`}
      ${i.management
        ? `<p class="manejo"${idiomaTexto ? ` lang="${idiomaTexto}"` : ""}><strong>${t("manejo_label")}</strong> ${escapeHtml(i.management)}</p>`
        : ""}
      <p class="meta">${FUENTE[i.source] || i.source}${
        // Un hallazgo armado con dos fuentes no se presenta como si fuera de una.
        i.severity_source
          ? ` ${t("gravedad_segun", { fuente: FUENTE[i.severity_source] || i.severity_source })}`
          : ""}</p>
    </article>`;
}

/* Duplicidad terapéutica. Dice qué regla la disparó —misma sustancia o clase de
   la AEMPS— y, si se suprimió, por qué: la procedencia es lo que VIDAL no da. */
function cardDuplicidad(d, suprimida) {
  const sev = suprimida ? "minor" : sevDuplicidad(d);
  const substancias = (d.substances || []).map(mostrar).join(", ");
  // `class_desc` es el grupo terapéutico de la AEMPS, en castellano: no se
  // traduce, va con `lang="es"` y, si la interfaz está en inglés, el aviso.
  const claseTexto = d.class_desc
    ? `<span lang="es">${escapeHtml(d.class_desc)}</span>` : escapeHtml(d.class_id);
  const titulo = d.layer === "substance"
    ? t("dup_titulo_sustancia")
    : `${t("dup_titulo_clase")} ${claseTexto}`;
  const detalle = d.layer === "substance"
    ? t("dup_detalle_sustancia", { sust: escapeHtml(substancias), n: escapeHtml(String(d.count)) })
    : t("dup_detalle_clase", {
        n: escapeHtml(String(d.count)), sust: escapeHtml(substancias),
        cupo: d.cupo == null ? "." : `${t("dup_cupo", { cupo: escapeHtml(String(d.cupo)) })}.`,
      });
  // Cuando la misma combinación cae en más de una clase, el médico tiene que
  // saber que no es sólo esta: si sólo mostramos una, parece más acotado de
  // lo que es.
  const otras = d.layer === "class" && (d.other_classes || []).length
    ? `<br>${t("dup_tambien_en")} ${d.other_classes
        .map((c) => `<span lang="es">${escapeHtml(c.class_desc || c.class_id)}</span>`).join(", ")}`
    : "";
  return `
    <article class="finding ${sev}">
      <div class="finding-head">
        <span class="pair">${titulo}</span>
        <span class="badge ${sev}">${suprimida ? t("dup_badge_no_alertada") : t("dup_badge_duplicidad")}</span>
      </div>
      <p class="evidence">${detalle}</p>
      ${d.class_desc && LANG === "en" ? notaFuenteIdioma("es") : ""}
      ${suprimida ? `<p class="manejo"><strong>${t("dup_motivo_label")}</strong>
          <span lang="es">${escapeHtml(d.motivo || "")}</span>${d.referencia ? ` (${escapeHtml(d.referencia)})` : ""}
          ${d.validado ? "" : ` ${t("dup_pendiente_validacion")}`}</p>` : ""}
      <p class="meta">${d.layer === "substance" ? FUENTE.consilio
        : `${FUENTE.aemps} — ${t("dup_grupo")} ${escapeHtml(d.class_id)}`}${otras}</p>
    </article>`;
}

function cardPaciente(c, sev) {
  return `
    <article class="finding ${sev}">
      <div class="finding-head">
        <span class="pair">${escapeHtml(mostrar(c.drug))}</span>
        <span class="badge ${sev}">${sev === "major" ? t("badge_contraindicado") : t("badge_precaucion")}</span>
      </div>
      <p class="evidence">${escapeHtml(condLabel(c.condition))}</p>
      <p class="meta">${FUENTE[c.source] || c.source}</p>
    </article>`;
}

/* Criterio de prescripción en el anciano.
   La mayoría viene condicionada a algo que no está en la receta —una
   comorbilidad, un valor de laboratorio—. Esas NO se muestran como una
   afirmación sobre el paciente: se muestran como una pregunta. Presentarlas
   como hechos sería falso en la mayoría de los casos, y es exactamente lo que
   hace que un médico deje de leer las alertas. */
function cardGeriatrica(g) {
  const cond = g.condicionada;
  return `
    <article class="finding ${cond ? "moderate" : "major"}">
      <div class="finding-head">
        <span class="pair">${escapeHtml(mostrar(g.drug))}</span>
        <span class="badge ${cond ? "moderate" : "major"}">${
          cond ? t("badge_verificar_65") : t("badge_evitar_65")}</span>
      </div>
      ${g.situacion
        ? `<p class="evidence">${cond ? `${t("geriatrica_aplica_si")} ` : ""}${escapeHtml(g.situacion)}</p>`
        : ""}
      <p class="manejo"><strong>${t("manejo_label")}</strong> ${escapeHtml(g.recomendacion)}</p>
      <p class="meta">${FUENTE[g.source] || g.source} ${t("geriatrica_meta")}</p>
    </article>`;
}

function cardAlergia(a) {
  return `
    <article class="finding major">
      <div class="finding-head">
        <span class="pair">${escapeHtml(mostrar(a.drug))}</span>
        <span class="badge major">${t("badge_alergia")}</span>
      </div>
      <p class="evidence">${t("alergia_evidencia_pre")}
        <strong>${escapeHtml(a.declared_as)}</strong>, ${t("alergia_evidencia_post")}</p>
      <p class="meta">${t("alergia_meta")}</p>
    </article>`;
}

/* ---------------- exportar ---------------- */

$("btn-imprimir").addEventListener("click", () => window.print());

$("btn-copiar").addEventListener("click", async () => {
  const { inter, contra } = ultimo;
  const L = [];
  L.push(t("copia_titulo"));
  L.push(new Date().toLocaleString(t("locale")));
  L.push("");
  L.push(t("copia_medicamentos", {
    lista: selected.map(nombreFarmaco).join(", ") || t("copia_sin_meds"),
  }));
  const p = perfil();
  const datos = [
    p.sexo && t("copia_sexo", { sexo: p.sexo }),
    p.edad !== null && t("copia_anios", { edad: p.edad }),
    p.embarazo && (p.semanas_gestacion
      ? t("copia_embarazo_semana", { n: p.semanas_gestacion }) : t("copia_embarazo")),
    p.lactancia && t("copia_lactancia"),
    p.funcion_renal && t("copia_renal", { v: p.funcion_renal }),
    p.funcion_hepatica && t("copia_hepatica", { v: p.funcion_hepatica }),
    p.alergias.length && t("copia_alergias", { lista: p.alergias.join(", ") }),
    patologias.length && t("copia_patologias", {
      lista: patologias.map((x) => `${x.code} ${condLabel(x.name)}`).join("; "),
    }),
  ].filter(Boolean);
  L.push(t("copia_paciente", { datos: datos.join(" · ") || t("copia_sin_datos") }));
  L.push("");

  (inter?.interactions || []).forEach((i) => {
    L.push(`[${(SEV[i.severity] || SEV.unknown).label.toUpperCase()}] ${mostrar(i.drug_a)} + ${mostrar(i.drug_b)}`);
    if (i.description) L.push(`  ${i.description}`);
    if (i.management) L.push(`  ${t("copia_qhacer", { texto: i.management })}`);
    L.push(`  ${t("copia_fuente", { fuente: FUENTE[i.source] || i.source })}`);
  });
  (inter?.duplicities || []).forEach((d) => {
    L.push(t("copia_dup", {
      que: d.layer === "substance" ? t("copia_dup_sustancia") : d.class_desc,
      sust: (d.substances || []).map(mostrar).join(", "),
    }));
  });
  (contra?.contraindications || []).forEach((c) =>
    L.push(t("copia_contraindicado", { drug: mostrar(c.drug), cond: condLabel(c.condition) })));
  (contra?.precautions || []).forEach((c) =>
    L.push(t("copia_precaucion", { drug: mostrar(c.drug), cond: condLabel(c.condition) })));
  (contra?.geriatric || []).forEach((g) => {
    L.push(`[${g.condicionada ? t("copia_verificar") : t("copia_evitar")} >65] ${mostrar(g.drug)}` +
           (g.situacion ? ` — ${g.situacion}` : ""));
    L.push(`  ${t("copia_qhacer", { texto: g.recomendacion })}`);
  });
  L.push("");
  L.push(t("disclaimer_1"));
  L.push(t("disclaimer_2"));

  try {
    await navigator.clipboard.writeText(L.join("\n"));
    toast(t("toast_copiado"));
  } catch {
    toast(t("toast_no_copiado"));
  }
});

/* ---------------- utilidades ---------------- */

function handleHttpError(r) {
  if (r.status === 503) {
    toast(t("toast_falta_key"), 8000);
  } else if (r.status === 401) {
    const k = prompt(t("prompt_api_key"));
    if (k) { localStorage.setItem("consilio_api_key", k); toast(t("toast_key_guardada")); }
  } else if (r.status === 429) {
    toast(t("toast_rate_limit"));
  } else {
    toast(t("toast_error_http", { status: r.status }));
  }
  return null;
}

const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const escapeAttr = escapeHtml;

/* ---------------- idioma ----------------
   `setLang()` (en i18n.js) ya tradujo el HTML estático y actualizó `LANG`
   antes de llamar acá. Lo que falta es todo lo que esta app arma en JS:
   píldoras de fármaco/patología (dependen de `LANG` en `mostrar`/`condLabel`)
   y, si ya hay una consulta hecha, los filtros y las tarjetas de resultado. */
function onLangChange() {
  actualizarTextoSemanas();
  renderDatos();
  meds.render(); alerg.render(); patol.render();
  syncButtons();
  if (ultimo.inter || ultimo.contra) {
    construirFiltros(ultimo.inter, ultimo.contra);
    render();
  }
}

syncButtons();
