/* Consilio — landing: rellena las cifras desde GET /data/summary.

   El HTML ya trae valores de respaldo (los del último deploy), así que la
   página se lee completa aunque esto falle. Pero si falla lo dice: presentar
   cifras viejas como si fueran en vivo es justo lo que la sección promete no
   hacer. */
(function () {
  "use strict";

  function get(obj, path) {
    return path.split(".").reduce(function (o, k) { return o == null ? undefined : o[k]; }, obj);
  }
  // Separador de miles con punto también para 4 cifras (1.971): el Intl de
  // "es" no agrupa números de 4 dígitos y la página quedaría inconsistente.
  function num(n) { return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, "."); }
  function pct(n) { return n.toFixed(1).replace(".", ",") + " %"; }
  function fecha(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return null;
    var p = function (x) { return String(x).padStart(2, "0"); };
    return p(d.getUTCDate()) + "/" + p(d.getUTCMonth() + 1) + "/" + d.getUTCFullYear();
  }
  function each(sel, fn) { Array.prototype.forEach.call(document.querySelectorAll(sel), fn); }

  function pintar(s) {
    each("[data-k]", function (el) {
      var v = get(s, el.getAttribute("data-k"));
      if (typeof v === "number") el.textContent = num(v);
    });
    each("[data-pct]", function (el) {
      var v = get(s, el.getAttribute("data-pct"));
      if (typeof v === "number") el.textContent = pct(v);
    });
    each("[data-count]", function (el) {
      var v = get(s, el.getAttribute("data-count"));
      if (v && typeof v === "object") el.textContent = num(Object.keys(v).length);
    });
    each("[data-date]", function (el) {
      var v = get(s, el.getAttribute("data-date"));
      var f = v && fecha(v);
      if (f) el.textContent = f;
    });
    each("[data-bar]", function (el) {
      var v = get(s, el.getAttribute("data-bar"));
      var t = get(s, el.getAttribute("data-of"));
      if (typeof v === "number" && t > 0) el.style.width = (100 * v / t).toFixed(2) + "%";
    });
    var estado = document.getElementById("estado-cifras");
    if (estado) {
      estado.textContent = "En vivo: leídas del sistema ahora mismo.";
      estado.classList.add("en-vivo");
    }
  }

  function cargar() {
    var ctl = "AbortController" in window ? new AbortController() : null;
    var t = ctl && setTimeout(function () { ctl.abort(); }, 8000);
    fetch("data/summary", { headers: { Accept: "application/json" }, signal: ctl && ctl.signal })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(pintar)
      .catch(function () {
        var estado = document.getElementById("estado-cifras");
        if (estado) estado.textContent = "No se pudo consultar el sistema en vivo: se muestran las cifras de respaldo al 26/09/2026.";
      })
      .then(function () { if (t) clearTimeout(t); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", cargar);
  else cargar();
})();
