/* Interfaz de consulta de Consilio.
   Vanilla, sin build: la app es un servicio, no un frontend, y meterle un
   toolchain de JS para dos pantallas sería costo sin beneficio.

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

const SEV = {
  major:    { label: "Grave",       rank: 0 },
  moderate: { label: "Moderada",    rank: 1 },
  minor:    { label: "Leve",        rank: 2 },
  unknown:  { label: "Sin graduar", rank: 3 },
};

const FUENTE = {
  aemps:     "AEMPS — Agencia Española de Medicamentos",
  ddinter:   "DDInter 2.0 — base curada de interacciones",
  openfda:   "openFDA — prospecto oficial de la FDA",
  medrt:     "MED-RT — Biblioteca Nacional de Medicina (EE.UU.)",
  recetalia: "Revisión propia de Consilio",
  perfil: "Dato cargado en el perfil del paciente",
};
// Canónico (inglés, el de la base) -> nombre para mostrar (castellano). Se va
// llenando con lo que devuelve el buscador: la base tiene 728 sustancias del
// DNMA y 73 alias manuales, así que buena parte del vademécum uruguayo se
// muestra en su grafía local en vez de en inglés.
const NOMBRE_ES = {};
const mostrar = (n) => NOMBRE_ES[n] || n;

const FUENTE_CORTA = {
  aemps: "AEMPS", ddinter: "DDInter", openfda: "openFDA",
  medrt: "MED-RT", recetalia: "Consilio", perfil: "Perfil",
};

// Receta de ejemplo: cada par de acá dispara algo distinto —una grave con
// texto, una por clase, una contra el perfil—, así se ve de qué es capaz sin
// que el usuario tenga que adivinar qué escribir.
const EJEMPLO = {
  drugs: ["warfarin", "ibuprofen", "simvastatin", "clarithromycin"],
  perfil: { edad: 72, renal: "moderada" },
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
      if (err !== "handled") toast("No se pudo consultar el servicio.");
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

  const respuestas = await Promise.all(qs.map(async (t) => {
    const r = await fetch(`/conditions/search?q=${encodeURIComponent(t)}&limit=10`,
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
    id: x.code, name: condEs(x.name), code: x.code, alertas: x.alertas,
  })).slice(0, 12);
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
  o.textContent = `semana ${w}`;
  semanasSel.appendChild(o);
}

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
  $("cnt-meds").textContent = n ? `${n} ${n === 1 ? "medicamento" : "medicamentos"}` : "";
  $("cnt-meds").hidden = !n;

  const pares = n * (n - 1) / 2;
  const r = $("resumen-cruce");
  r.hidden = n < 1;
  if (n >= 2) {
    r.innerHTML = `Se van a cruzar <strong>${pares}</strong>
      ${pares === 1 ? "combinación" : "combinaciones"} entre sí,
      y cada medicamento contra el perfil del paciente.`;
  } else if (n === 1) {
    r.innerHTML = `Con un solo medicamento no hay combinaciones que cruzar.
      Agregá otro, o completá el perfil para cruzarlo contra el paciente.`;
  }

  const campos = [
    $("sexo").value, $("edad").value, $("renal").value, $("hepatica").value,
    $("embarazo").checked ? "1" : "", $("lactancia").checked ? "1" : "",
  ].filter(Boolean).length + alergias.length + patologias.length;
  $("cnt-perfil").textContent = campos ? `${campos} ${campos === 1 ? "dato" : "datos"}` : "";
  $("cnt-perfil").hidden = !campos;
}

const meds = wireSearch({
  input: $("q"), list: $("suggestions"), target: selected, chips: $("chips"),
  onChange: syncButtons, fetchFn: buscarFarmacos,
  renderItem: (r) => `<span class="nombre">${escapeHtml(r.name_es || r.name)}${
    r.name_es ? `<span class="alias-en"> · ${escapeHtml(r.name)}</span>` : ""}</span>${
    r.rxcui ? `<span class="rxcui">RxCUI ${r.rxcui}</span>` : ""}`,
  renderChip: (s) => escapeHtml(s.name_es || s.name),
});
const alerg = wireSearch({
  input: $("qa"), list: $("suggestions-alergias"), target: alergias,
  chips: $("chips-alergias"), onChange: syncButtons, fetchFn: buscarFarmacos,
  renderItem: (r) => `<span class="nombre">${escapeHtml(r.name_es || r.name)}</span>`,
  renderChip: (s) => escapeHtml(s.name_es || s.name),
});
const patol = wireSearch({
  input: $("qp"), list: $("suggestions-patologias"), target: patologias,
  chips: $("chips-patologias"), onChange: syncButtons, fetchFn: buscarPatologias,
  // Se muestra cuántas alertas cuelgan del código: es la única forma de que el
  // médico sepa, antes de elegirlo, si ese código va a evaluar algo.
  renderItem: (r) => `<span class="code">${escapeHtml(r.code)}</span>
    <span class="nombre">${escapeHtml(r.name)}</span>
    <span class="alertas">${r.alertas} ${r.alertas === 1 ? "alerta" : "alertas"}</span>`,
  renderChip: (s) => `<span class="code">${escapeHtml(s.code)}</span> ${escapeHtml(s.name)}`,
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

$("btn-ayuda").addEventListener("click", (e) => {
  const abierto = $("ayuda").hidden;
  $("ayuda").hidden = !abierto;
  e.currentTarget.setAttribute("aria-expanded", String(abierto));
});

$("btn-ejemplo").addEventListener("click", async () => {
  selected.length = 0;
  for (const nombre of EJEMPLO.drugs) {
    try {
      const res = await buscarFarmacos(nombre);
      const exacto = res.find((r) => r.name.toLowerCase() === nombre) || res[0];
      if (exacto) selected.push(exacto);
    } catch { /* si falla uno, se cargan los demás */ }
  }
  $("edad").value = EJEMPLO.perfil.edad;
  $("renal").value = EJEMPLO.perfil.renal;
  SELECTS.renal.sync();
  $("aviso-edad").hidden = false;
  invalidateResults();
  meds.render();
  syncButtons();
  if (!selected.length) toast("No se pudo cargar el ejemplo.");
  else $("check").focus();
});

/* ---------------- consulta ---------------- */

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !$("check").disabled) {
    e.preventDefault();
    $("check").click();
  }
});

$("check").addEventListener("click", async () => {
  const btn = $("check");
  btn.disabled = true;
  btn.textContent = "Consultando…";
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
    toast("No se pudo consultar el servicio.");
    interError = contraError = "No se pudo contactar al servicio.";
  }
  btn.textContent = "Consultar";
  syncButtons();
  // Fuera del try: un error al pintar no puede disfrazarse de error de red.
  ultimo = { inter, contra, interError, contraError };
  construirFiltros(inter, contra);
  render();
});

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

/* ---------------- filtros ----------------
   Se arman sobre lo que efectivamente se encontró: ofrecer un filtro "Leve"
   cuando no hay ninguna leve es prometer algo que no está. */

const filtro = {
  sev: new Set(), fuente: new Set(), conTexto: false, sinInferidas: false, texto: "",
};

function construirFiltros(inter, contra) {
  const hallazgos = (inter?.interactions || []);
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
  html += '<div class="col"><p class="col-title">Alertas medicamento — medicamento</p>';
  if (inter) {
    const todos = (inter.interactions || []).slice()
      .sort((a, b) => (SEV[a.severity]?.rank ?? 9) - (SEV[b.severity]?.rank ?? 9));
    const found = todos.filter(pasaFiltro);
    ocultos += todos.length - found.length;
    const pares = selected.length * (selected.length - 1) / 2;
    html += found.map(cardInteraccion).join("");
    if (!found.length && todos.length) {
      html += '<div class="empty-state">Ningún hallazgo coincide con los filtros.</div>';
    }
    const sin = pares - todos.length;
    if (sin > 0 && !hayFiltro()) {
      // Nunca "es seguro": decimos que no encontramos evidencia.
      html += `<div class="empty-state"><strong>${sin}
        ${sin === 1 ? "combinación" : "combinaciones"} sin evidencia encontrada.</strong>
        Que no hayamos encontrado una interacción documentada no significa que no exista.</div>`;
    }
  } else if (interError) {
    html += cardError("No se pudieron evaluar las interacciones", interError);
  } else {
    html += '<div class="empty-state">Agregá dos o más medicamentos para cruzarlos entre sí.</div>';
  }
  html += "</div>";

  /* --- columna 2: medicamento <-> paciente --- */
  html += '<div class="col"><p class="col-title">Alertas medicamento — paciente</p>';
  if (contra) {
    (contra.profile_warnings || []).forEach((w) => {
      html += `<div class="aviso-perfil">${escapeHtml(w)}</div>`;
    });
    const al = (contra.allergies || []).filter((a) => a.match === "exact")
      .filter((a) => pasaFiltroPaciente([a.drug, a.declared_as], "major", "perfil"));
    const noId = (contra.allergies || []).filter((a) => a.match === "unresolved");
    const ci = (contra.contraindications || [])
      .filter((c) => pasaFiltroPaciente([c.drug, condEs(c.condition)], "major", c.source));
    const pre = (contra.precautions || [])
      .filter((c) => pasaFiltroPaciente([c.drug, condEs(c.condition)], "moderate", c.source));
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
        html += `<div class="empty-state">No se pudo identificar
          <strong>${escapeHtml(a.declared_as)}</strong> como medicamento, así que esa
          alergia no se tuvo en cuenta.</div>`;
      });
      (contra.not_evaluated || []).forEach((n) => {
        html += `<div class="empty-state"><strong>${escapeHtml(n.drug || n.icd10)}</strong>
          no se pudo evaluar: ${escapeHtml(n.reason)}.</div>`;
      });
    }

    const total = al.length + ci.length + pre.length + geri.length;
    if (total === 0 && !noId.length) {
      html += hayFiltro()
        ? '<div class="empty-state">Ningún hallazgo coincide con los filtros.</div>'
        : `<div class="empty-state"><strong>Sin alertas para este perfil.</strong>
             Se evalúan embarazo y semana de gestación, lactancia, función renal y
             hepática, alergias declaradas, patologías por CIE-10 y, desde los 65
             años, los criterios de prescripción en el anciano.</div>`;
    }
  } else if (contraError) {
    html += cardError("No se pudieron evaluar las alertas contra el paciente", contraError);
  } else {
    html += '<div class="empty-state">Completá el perfil del paciente para cruzarlo contra los medicamentos.</div>';
  }
  html += "</div></div>";

  $("results-body").innerHTML = html;
  box.hidden = false;

  $("f-reset").hidden = !hayFiltro();
  $("filtro-estado").hidden = !ocultos;
  $("filtro-estado").textContent = ocultos
    ? `${ocultos} ${ocultos === 1 ? "hallazgo oculto" : "hallazgos ocultos"} por los filtros.` : "";

  const cov = (inter && inter.coverage_summary) || {};
  const partes = Object.entries(cov).filter(([k, n]) => n > 0 && k !== "unknown")
    .map(([k, n]) => `${n} de ${FUENTE[k] || k}`);
  if (contra && ((contra.contraindications || []).length || (contra.precautions || []).length)) {
    partes.push(FUENTE.medrt);
  }
  $("sources").textContent = partes.length ? `Fuentes consultadas: ${partes.join(" · ")}.` : "";
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function descripcionError(r) {
  if (r.status === 401) return "El servicio pidió una API key.";
  if (r.status === 429) return "Demasiadas consultas seguidas.";
  if (r.status === 503) return "El servicio no está disponible.";
  return `El servicio respondió con un error ${r.status}.`;
}

/* Una consulta que falló NO se pinta como un resultado vacío. Es la diferencia
   entre "no hay alertas" y "no sabemos si hay alertas", y en una receta esa
   diferencia es todo. */
function cardError(titulo, detalle) {
  return `
    <div class="error-state">
      <strong>${escapeHtml(titulo)}</strong>
      <p>${escapeHtml(detalle)} Los resultados de esta columna están incompletos:
         <strong>no interpretar el vacío como ausencia de alertas.</strong></p>
      <button type="button" class="btn-ghost" onclick="document.getElementById('check').click()">
        Reintentar</button>
    </div>`;
}

function cardInteraccion(i) {
  const sev = SEV[i.severity] ? i.severity : "unknown";
  // El modo de match sólo se muestra cuando la regla fue de CLASE: es menos
  // específica que una de molécula y el médico tiene derecho a saberlo.
  const porClase = (i.text_match || "").includes("clase");
  return `
    <article class="finding ${sev}">
      <div class="finding-head">
        <span class="pair">${escapeHtml(mostrar(i.drug_a))} + ${escapeHtml(mostrar(i.drug_b))}</span>
        <span class="badge ${sev}">${SEV[sev].label}</span>
        ${i.uncertain ? '<span class="tag-uncertain">inferida de texto</span>' : ""}
        ${porClase ? '<span class="tag-clase">regla de clase</span>' : ""}
      </div>
      ${i.description
        ? `<p class="evidence"${i.source === "openfda" ? ' lang="en"' : ""}>${
             escapeHtml(i.description)}</p>${
             i.source === "openfda"
               ? '<p class="evidence-note">Texto original del prospecto, en inglés.</p>' : ""}`
        : `<p class="evidence sin-texto">${sev === "unknown"
             ? "La fuente registra el par pero no lo gradúa ni describe el mecanismo."
             : "La fuente registra el par y su gravedad, pero no aporta descripción del mecanismo."}</p>`}
      ${i.management
        ? `<p class="manejo"><strong>Qué hacer:</strong> ${escapeHtml(i.management)}</p>`
        : ""}
      <p class="meta">${FUENTE[i.source] || i.source}${
        // Un hallazgo armado con dos fuentes no se presenta como si fuera de una.
        i.severity_source
          ? ` · gravedad según ${FUENTE[i.severity_source] || i.severity_source}`
          : ""}</p>
    </article>`;
}

function cardPaciente(c, sev) {
  return `
    <article class="finding ${sev}">
      <div class="finding-head">
        <span class="pair">${escapeHtml(mostrar(c.drug))}</span>
        <span class="badge ${sev}">${sev === "major" ? "Contraindicado" : "Precaución"}</span>
      </div>
      <p class="evidence">${escapeHtml(condEs(c.condition))}</p>
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
          cond ? "Verificar — mayor de 65" : "Evitar — mayor de 65"}</span>
      </div>
      ${g.situacion
        ? `<p class="evidence">${cond ? "Aplica si: " : ""}${escapeHtml(g.situacion)}</p>`
        : ""}
      <p class="manejo"><strong>Qué hacer:</strong> ${escapeHtml(g.recomendacion)}</p>
      <p class="meta">${FUENTE[g.source] || g.source} — criterios de prescripción
        en el anciano</p>
    </article>`;
}

function cardAlergia(a) {
  return `
    <article class="finding major">
      <div class="finding-head">
        <span class="pair">${escapeHtml(mostrar(a.drug))}</span>
        <span class="badge major">Alergia declarada</span>
      </div>
      <p class="evidence">El paciente declaró alergia a
        <strong>${escapeHtml(a.declared_as)}</strong>, que es este mismo fármaco.</p>
      <p class="meta">Perfil del paciente</p>
    </article>`;
}

/* ---------------- exportar ---------------- */

$("btn-imprimir").addEventListener("click", () => window.print());

$("btn-copiar").addEventListener("click", async () => {
  const { inter, contra } = ultimo;
  const L = [];
  L.push("CONSILIO — consulta de seguridad en la prescripción");
  L.push(new Date().toLocaleString("es-UY"));
  L.push("");
  L.push(`Medicamentos: ${selected.map((s) => s.name_es || s.name).join(", ") || "—"}`);
  const p = perfil();
  const datos = [
    p.sexo && `sexo ${p.sexo}`, p.edad !== null && `${p.edad} años`,
    p.embarazo && (p.semanas_gestacion ? `embarazo semana ${p.semanas_gestacion}` : "embarazo"),
    p.lactancia && "lactancia",
    p.funcion_renal && `función renal ${p.funcion_renal}`,
    p.funcion_hepatica && `función hepática ${p.funcion_hepatica}`,
    p.alergias.length && `alergias: ${p.alergias.join(", ")}`,
    patologias.length && `patologías: ${patologias.map((x) => `${x.code} ${x.name}`).join("; ")}`,
  ].filter(Boolean);
  L.push(`Paciente: ${datos.join(" · ") || "sin datos"}`);
  L.push("");

  (inter?.interactions || []).forEach((i) => {
    L.push(`[${(SEV[i.severity] || SEV.unknown).label.toUpperCase()}] ${mostrar(i.drug_a)} + ${mostrar(i.drug_b)}`);
    if (i.description) L.push(`  ${i.description}`);
    if (i.management) L.push(`  Qué hacer: ${i.management}`);
    L.push(`  Fuente: ${FUENTE[i.source] || i.source}`);
  });
  (contra?.contraindications || []).forEach((c) =>
    L.push(`[CONTRAINDICADO] ${mostrar(c.drug)} — ${condEs(c.condition)}`));
  (contra?.precautions || []).forEach((c) =>
    L.push(`[PRECAUCIÓN] ${mostrar(c.drug)} — ${condEs(c.condition)}`));
  (contra?.geriatric || []).forEach((g) => {
    L.push(`[${g.condicionada ? "VERIFICAR" : "EVITAR"} >65] ${mostrar(g.drug)}` +
           (g.situacion ? ` — ${g.situacion}` : ""));
    L.push(`  Qué hacer: ${g.recomendacion}`);
  });
  L.push("");
  L.push("Información generada automáticamente a partir de fuentes públicas.");
  L.push("No sustituye el criterio clínico.");

  try {
    await navigator.clipboard.writeText(L.join("\n"));
    toast("Resumen copiado al portapapeles.");
  } catch {
    toast("El navegador no permitió copiar. Usá Imprimir.");
  }
});

/* ---------------- utilidades ---------------- */

function handleHttpError(r) {
  if (r.status === 503) {
    toast("El servicio está mal configurado: falta la API key del servidor.", 8000);
  } else if (r.status === 401) {
    const k = prompt("Este servicio requiere API key:");
    if (k) { localStorage.setItem("consilio_api_key", k); toast("Guardada. Probá de nuevo."); }
  } else if (r.status === 429) {
    toast("Demasiadas consultas seguidas. Esperá unos segundos.");
  } else {
    toast(`Error del servicio (${r.status}).`);
  }
  return null;
}

const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const escapeAttr = escapeHtml;

syncButtons();
