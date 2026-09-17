/* Interfaz de consulta de Consilio.
   Vanilla, sin build: la app es un servicio, no un frontend, y meterle un
   toolchain de JS para dos pantallas sería costo sin beneficio. */

const $ = (id) => document.getElementById(id);
const selected = [];           // medicamentos a recetar
const alergias = [];           // fármacos a los que el paciente reaccionó

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
  ddinter:   "DDInter 2.0 — base curada de interacciones",
  openfda:   "openFDA — prospecto oficial de la FDA",
  medrt:     "MED-RT — Biblioteca Nacional de Medicina (EE.UU.)",
  recetalia: "Revisión propia de Consilio",
};

// Los descriptores de MED-RT están en inglés. Se traducen los que efectivamente
// se pueden disparar hoy; el resto se muestra tal cual, que es preferible a una
// traducción inventada en contexto clínico.
const CONDICION_ES = {
  "Pregnancy": "Embarazo",
  "Pregnancy Trimester, First": "Embarazo — primer trimestre",
  "Pregnancy Trimester, Second": "Embarazo — segundo trimestre",
  "Pregnancy Trimester, Third": "Embarazo — tercer trimestre",
  "Lactation": "Lactancia",
  "Breast Feeding": "Lactancia",
  "Renal Insufficiency": "Insuficiencia renal",
  "Renal Insufficiency, Chronic": "Insuficiencia renal crónica",
  "Kidney Diseases": "Enfermedad renal",
  "Liver Diseases": "Enfermedad hepática",
  "Liver Failure": "Insuficiencia hepática",
  "Hepatic Insufficiency": "Insuficiencia hepática",
  "Liver Cirrhosis": "Cirrosis hepática",
};
const condEs = (n) => CONDICION_ES[n] || n;

function toast(msg, ms = 4500) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

/* ---------------- autocompletado (reusable) ---------------- */

function wireSearch({ input, list, target, chips, onChange }) {
  let timer = null;

  input.addEventListener("input", (e) => {
    const q = e.target.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { list.hidden = true; return; }
    timer = setTimeout(() => run(q), 180);   // sin debounce, una request por tecla
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
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = cur >= 0 ? items[cur] : items[0];
      if (pick) add(Number(pick.dataset.id), pick.dataset.name);
    } else if (e.key === "Escape") {
      list.hidden = true;
    }
  });

  async function run(q) {
    let data;
    try {
      const r = await fetch(`/drugs/search?q=${encodeURIComponent(q)}&limit=10`,
                            { headers: headers() });
      if (!r.ok) { handleHttpError(r); return; }
      data = await r.json();
    } catch { toast("No se pudo consultar el servicio."); return; }

    const fresh = (data.results || []).filter(
      (r) => !target.some((s) => s.drug_id === r.drug_id));
    if (!fresh.length) {
      list.innerHTML = '<li class="empty">Sin resultados</li>';
      list.hidden = false;
      return;
    }
    list.innerHTML = fresh.map((r, i) => `
      <li data-id="${r.drug_id}" data-name="${escapeAttr(r.name)}" aria-selected="${i === 0}">
        ${escapeHtml(r.name)}${r.rxcui ? `<span class="rxcui">RxCUI ${r.rxcui}</span>` : ""}
      </li>`).join("");
    list.querySelectorAll("li[data-id]").forEach((li) =>
      li.addEventListener("click", () => add(Number(li.dataset.id), li.dataset.name)));
    list.hidden = false;
  }

  function add(id, name) {
    if (!target.some((s) => s.drug_id === id)) target.push({ drug_id: id, name });
    input.value = "";
    list.hidden = true;
    invalidateResults();
    render();
    input.focus();
  }

  function render() {
    chips.innerHTML = target.map((s) => `
      <li>${escapeHtml(s.name)}
        <button type="button" aria-label="Quitar ${escapeAttr(s.name)}"
                data-id="${s.drug_id}">&times;</button>
      </li>`).join("");
    chips.querySelectorAll("button").forEach((b) =>
      b.addEventListener("click", () => {
        const i = target.findIndex((s) => s.drug_id === Number(b.dataset.id));
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

/* ---------------- perfil ---------------- */

const semanasSel = $("semanas");
for (let w = 1; w <= 42; w++) {
  const o = document.createElement("option");
  o.value = String(w);
  o.textContent = `semana ${w}`;
  semanasSel.appendChild(o);
}

$("sexo").addEventListener("change", (e) => {
  // Embarazo y lactancia sólo se ofrecen con sexo femenino declarado. Si se
  // cambia a masculino se limpian, para no mandar un perfil incoherente.
  const f = e.target.value === "F";
  $("gestacion").hidden = !f;
  if (!f) {
    $("embarazo").checked = false;
    $("lactancia").checked = false;
    semanasSel.value = "";
    semanasSel.disabled = true;
  }
  invalidateResults();
  syncButtons();
});

$("embarazo").addEventListener("change", (e) => {
  semanasSel.disabled = !e.target.checked;
  if (!e.target.checked) semanasSel.value = "";
  invalidateResults();
  syncButtons();
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
  };
}

const hayPerfil = () => {
  const p = perfil();
  return Boolean(p.embarazo || p.lactancia || p.funcion_renal ||
                 p.funcion_hepatica || p.alergias.length);
};

/* ---------------- estado ---------------- */

function invalidateResults() {
  const box = $("results");
  if (!box.hidden) {
    box.hidden = true;
    box.innerHTML = "";
    $("sources").textContent = "";
  }
}

function syncButtons() {
  // Con un solo medicamento no hay pares que cruzar, pero sí puede haber
  // alertas contra el paciente. Por eso alcanza con uno si hay perfil.
  $("check").disabled = selected.length < 2 && !(selected.length === 1 && hayPerfil());
  $("clear").hidden = selected.length === 0 && alergias.length === 0;
}

const meds = wireSearch({
  input: $("q"), list: $("suggestions"), target: selected,
  chips: $("chips"), onChange: syncButtons,
});
const alerg = wireSearch({
  input: $("qa"), list: $("suggestions-alergias"), target: alergias,
  chips: $("chips-alergias"), onChange: syncButtons,
});

$("clear").addEventListener("click", () => {
  selected.length = 0;
  alergias.length = 0;
  ["sexo", "edad", "renal", "hepatica"].forEach((id) => { $(id).value = ""; });
  $("embarazo").checked = false;
  $("lactancia").checked = false;
  semanasSel.value = "";
  semanasSel.disabled = true;
  $("gestacion").hidden = true;
  invalidateResults();
  meds.render();
  alerg.render();
});

/* ---------------- consulta ---------------- */

$("check").addEventListener("click", async () => {
  const btn = $("check");
  btn.disabled = true;
  btn.textContent = "Consultando…";
  const drugs = selected.map((s) => s.name);
  let inter = null, contra = null;

  try {
    const calls = [];
    if (drugs.length >= 2) {
      calls.push(fetch("/interactions", {
        method: "POST", headers: headers(), body: JSON.stringify({ drugs }),
      }).then(async (r) => { inter = r.ok ? await r.json() : handleHttpError(r); }));
    }
    if (hayPerfil()) {
      calls.push(fetch("/contraindications", {
        method: "POST", headers: headers(),
        body: JSON.stringify({ drugs, profile: perfil() }),
      }).then(async (r) => { contra = r.ok ? await r.json() : handleHttpError(r); }));
    }
    await Promise.all(calls);
  } catch {
    toast("No se pudo consultar el servicio.");
    btn.textContent = "Consultar";
    syncButtons();
    return;
  }
  btn.textContent = "Consultar";
  syncButtons();
  // Fuera del try: un error al pintar no puede disfrazarse de error de red.
  render(inter, contra);
});

function render(inter, contra) {
  const box = $("results");
  let html = '<div class="cols">';

  /* --- columna 1: medicamento <-> medicamento --- */
  html += '<div class="col"><p class="col-title">Alertas medicamento — medicamento</p>';
  if (inter) {
    const found = (inter.interactions || []).slice()
      .sort((a, b) => (SEV[a.severity]?.rank ?? 9) - (SEV[b.severity]?.rank ?? 9));
    const pares = selected.length * (selected.length - 1) / 2;
    html += found.map(cardInteraccion).join("");
    const sin = pares - found.length;
    if (sin > 0) {
      // Nunca "es seguro": decimos que no encontramos evidencia.
      html += `<div class="empty-state"><strong>${sin}
        ${sin === 1 ? "combinación" : "combinaciones"} sin evidencia encontrada.</strong>
        Que no hayamos encontrado una interacción documentada no significa que no exista.</div>`;
    }
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
    const al = (contra.allergies || []).filter((a) => a.match === "exact");
    const noId = (contra.allergies || []).filter((a) => a.match === "unresolved");
    html += al.map(cardAlergia).join("");
    html += (contra.contraindications || []).map((c) => cardPaciente(c, "major")).join("");
    html += (contra.precautions || []).map((c) => cardPaciente(c, "moderate")).join("");

    // Lo que no se pudo evaluar se dice, no se omite.
    noId.forEach((a) => {
      html += `<div class="empty-state">No se pudo identificar
        <strong>${escapeHtml(a.declared_as)}</strong> como medicamento, así que esa
        alergia no se tuvo en cuenta.</div>`;
    });
    (contra.not_evaluated || []).forEach((n) => {
      html += `<div class="empty-state"><strong>${escapeHtml(n.drug)}</strong>
        no se pudo evaluar: ${escapeHtml(n.reason)}.</div>`;
    });

    const total = al.length + (contra.contraindications || []).length +
                  (contra.precautions || []).length;
    if (total === 0 && !noId.length) {
      html += `<div class="empty-state"><strong>Sin alertas para este perfil.</strong>
        Hoy se evalúan embarazo, lactancia, función renal y hepática, y las
        alergias declaradas.</div>`;
    }
  } else {
    html += '<div class="empty-state">Completá el perfil del paciente para cruzarlo contra los medicamentos.</div>';
  }
  html += "</div></div>";

  box.innerHTML = html;
  box.hidden = false;

  const cov = (inter && inter.coverage_summary) || {};
  const partes = Object.entries(cov).filter(([k, n]) => n > 0 && k !== "unknown")
    .map(([k, n]) => `${n} de ${FUENTE[k] || k}`);
  if (contra && ((contra.contraindications || []).length || (contra.precautions || []).length)) {
    partes.push(FUENTE.medrt);
  }
  $("sources").textContent = partes.length ? `Fuentes consultadas: ${partes.join(" · ")}.` : "";
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function cardInteraccion(i) {
  const sev = SEV[i.severity] ? i.severity : "unknown";
  return `
    <article class="finding ${sev}">
      <div class="finding-head">
        <span class="pair">${escapeHtml(i.drug_a)} + ${escapeHtml(i.drug_b)}</span>
        <span class="badge ${sev}">${SEV[sev].label}</span>
        ${i.uncertain ? '<span class="tag-uncertain">inferida de texto</span>' : ""}
      </div>
      ${i.description
        ? `<p class="evidence"${i.source === "openfda" ? ' lang="en"' : ""}>${
             escapeHtml(i.description)}</p>${
             i.source === "openfda"
               ? '<p class="evidence-note">Texto original del prospecto, en inglés.</p>' : ""}`
        : `<p class="evidence sin-texto">La fuente registra el par y su gravedad,
             pero no aporta descripción del mecanismo.</p>`}
      <p class="meta">${FUENTE[i.source] || i.source}</p>
    </article>`;
}

function cardPaciente(c, sev) {
  return `
    <article class="finding ${sev}">
      <div class="finding-head">
        <span class="pair">${escapeHtml(c.drug)}</span>
        <span class="badge ${sev}">${sev === "major" ? "Contraindicado" : "Precaución"}</span>
      </div>
      <p class="evidence">${escapeHtml(condEs(c.condition))}</p>
      <p class="meta">${FUENTE[c.source] || c.source}</p>
    </article>`;
}

function cardAlergia(a) {
  return `
    <article class="finding major">
      <div class="finding-head">
        <span class="pair">${escapeHtml(a.drug)}</span>
        <span class="badge major">Alergia declarada</span>
      </div>
      <p class="evidence">El paciente declaró alergia a
        <strong>${escapeHtml(a.declared_as)}</strong>, que es este mismo fármaco.</p>
      <p class="meta">Perfil del paciente</p>
    </article>`;
}

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
