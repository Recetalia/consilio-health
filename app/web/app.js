/* Interfaz de consulta de Consilio.
   Vanilla, sin build: la app es un servicio, no un frontend, y meterle un
   toolchain de JS para una pantalla sería costo sin beneficio. */

const $ = (id) => document.getElementById(id);
const selected = [];           // [{drug_id, name}]

// La key vive en localStorage. En desarrollo el servicio corre con
// CONSILIO_ALLOW_NO_API_KEY=1 y no hace falta.
const apiKey = () => localStorage.getItem("consilio_api_key") || "";
const headers = () => {
  const h = { "Content-Type": "application/json" };
  const k = apiKey();
  if (k) h["X-API-Key"] = k;
  return h;
};

const SEV = {
  major:     { label: "Grave",        rank: 0 },
  moderate:  { label: "Moderada",     rank: 1 },
  minor:     { label: "Leve",         rank: 2 },
  unknown:   { label: "Sin graduar",  rank: 3 },
};

const FUENTE = {
  ddinter:   "DDInter 2.0 — base curada de interacciones",
  openfda:   "openFDA — prospecto oficial de la FDA",
  recetalia: "Revisión propia de Consilio",
};

function toast(msg, ms = 4000) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

/* ---------------- autocompletado ---------------- */

let searchTimer = null;

$("q").addEventListener("input", (e) => {
  const q = e.target.value.trim();
  clearTimeout(searchTimer);
  if (q.length < 2) { hideSuggestions(); return; }
  // Debounce: sin esto se dispara una request por tecla.
  searchTimer = setTimeout(() => runSearch(q), 180);
});

$("q").addEventListener("keydown", (e) => {
  const items = [...$("suggestions").querySelectorAll("li[data-id]")];
  if (!items.length) return;
  const cur = items.findIndex((li) => li.getAttribute("aria-selected") === "true");
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const next = e.key === "ArrowDown"
      ? Math.min(cur + 1, items.length - 1)
      : Math.max(cur - 1, 0);
    items.forEach((li, i) => li.setAttribute("aria-selected", i === next));
  } else if (e.key === "Enter") {
    e.preventDefault();
    const pick = cur >= 0 ? items[cur] : items[0];
    if (pick) addDrug(Number(pick.dataset.id), pick.dataset.name);
  } else if (e.key === "Escape") {
    hideSuggestions();
  }
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".search")) hideSuggestions();
});

async function runSearch(q) {
  let data;
  try {
    const r = await fetch(`/drugs/search?q=${encodeURIComponent(q)}&limit=10`,
                          { headers: headers() });
    if (!r.ok) return handleHttpError(r);
    data = await r.json();
  } catch {
    toast("No se pudo consultar el servicio.");
    return;
  }
  renderSuggestions(data.results || []);
}

function renderSuggestions(results) {
  const ul = $("suggestions");
  const fresh = results.filter((r) => !selected.some((s) => s.drug_id === r.drug_id));
  if (!fresh.length) {
    ul.innerHTML = '<li class="empty">Sin resultados</li>';
    ul.hidden = false;
    return;
  }
  ul.innerHTML = fresh.map((r, i) => `
    <li data-id="${r.drug_id}" data-name="${escapeAttr(r.name)}"
        aria-selected="${i === 0}">
      ${escapeHtml(r.name)}${r.rxcui ? `<span class="rxcui">RxCUI ${r.rxcui}</span>` : ""}
    </li>`).join("");
  ul.querySelectorAll("li[data-id]").forEach((li) => {
    li.addEventListener("click", () => addDrug(Number(li.dataset.id), li.dataset.name));
  });
  ul.hidden = false;
}

const hideSuggestions = () => { $("suggestions").hidden = true; };

/* ---------------- selección ---------------- */

function invalidateResults() {
  const box = $("results");
  if (!box.hidden) {
    box.hidden = true;
    box.innerHTML = "";
    $("sources").textContent = "";
  }
}

function addDrug(id, name) {
  if (!selected.some((s) => s.drug_id === id)) selected.push({ drug_id: id, name });
  invalidateResults();
  $("q").value = "";
  hideSuggestions();
  renderChips();
  $("q").focus();
}

function removeDrug(id) {
  const i = selected.findIndex((s) => s.drug_id === id);
  if (i >= 0) selected.splice(i, 1);
  invalidateResults();
  renderChips();
}

function renderChips() {
  $("chips").innerHTML = selected.map((s) => `
    <li>${escapeHtml(s.name)}
      <button type="button" aria-label="Quitar ${escapeAttr(s.name)}"
              data-id="${s.drug_id}">&times;</button>
    </li>`).join("");
  $("chips").querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => removeDrug(Number(b.dataset.id)));
  });
  $("check").disabled = selected.length < 2;
  $("clear").hidden = selected.length === 0;
}

$("clear").addEventListener("click", () => {
  selected.length = 0;
  renderChips();
  $("results").hidden = true;
  $("sources").textContent = "";
});

/* ---------------- consulta ---------------- */

$("check").addEventListener("click", async () => {
  const btn = $("check");
  btn.disabled = true;
  btn.textContent = "Consultando…";
  let data;
  try {
    const r = await fetch("/interactions", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ drugs: selected.map((s) => s.name) }),
    });
    if (!r.ok) { handleHttpError(r); return; }
    data = await r.json();
  } catch {
    toast("No se pudo consultar el servicio.");
    return;
  } finally {
    btn.textContent = "Consultar";
    btn.disabled = selected.length < 2;
  }
  // El render va FUERA del try. Adentro, un error al pintar disparaba el toast
  // de "no se pudo consultar" sobre una consulta que había respondido 200 y ya
  // se había pintado: el usuario veía los resultados correctos y un cartel de
  // error al mismo tiempo.
  render(data);
});

function render(data) {
  const box = $("results");
  const found = (data.interactions || []).slice()
    .sort((a, b) => (SEV[a.severity]?.rank ?? 9) - (SEV[b.severity]?.rank ?? 9));

  const pairs = selected.length * (selected.length - 1) / 2;
  const sinHallazgo = pairs - found.length;

  let html = "";

  if (found.length) {
    html += `<div class="result-group">
      <p class="group-title">${found.length} ${found.length === 1 ? "hallazgo" : "hallazgos"}</p>
      ${found.map(card).join("")}
    </div>`;
  }

  // Nunca decimos "es seguro": decimos que no encontramos evidencia. No es lo
  // mismo, y confundirlos es el modo en que esta clase de herramienta hace daño.
  if (sinHallazgo > 0) {
    html += `<div class="empty-state">
      <strong>${sinHallazgo} ${sinHallazgo === 1 ? "combinación" : "combinaciones"}
      sin evidencia encontrada.</strong>
      Que no hayamos encontrado una interacción documentada no significa que no exista.
    </div>`;
  }

  box.innerHTML = html;
  box.hidden = false;

  const cov = data.coverage_summary || {};
  const partes = Object.entries(cov).filter(([k, n]) => n > 0 && k_ok(k))
    .map(([k, n]) => `${n} de ${FUENTE[k] || k}`);
  $("sources").textContent = partes.length
    ? `Fuentes consultadas: ${partes.join(" · ")}.`
    : "";
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// 'unknown' no es una fuente: es el bucket de lo que no resolvió.
const k_ok = (k) => k !== "unknown";

function card(i) {
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
               ? '<p class="evidence-note">Texto original del prospecto, en inglés.</p>'
               : ""}`
        : `<p class="evidence sin-texto">La fuente registra el par y su gravedad,
             pero no aporta descripción del mecanismo.</p>`}
      <p class="meta">${FUENTE[i.source] || i.source}${
        i.management ? `<span class="dot">·</span>${escapeHtml(i.management)}` : ""}</p>
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
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const escapeAttr = escapeHtml;

renderChips();
