/* i18n.js — selector de idioma castellano/inglés de la interfaz de Consilio.

   Sólo se traduce la UI (esta app). El contenido clínico NO se traduce
   automáticamente:
     - nombres de fármacos: se muestra `name_es` (traducción manual del
       DNMA/alias) en castellano, o el canónico (inglés) en inglés — ver
       `mostrar()` en app.js.
     - patologías: se muestra `condEs()` (144 traducciones a mano) en
       castellano, o el nombre MeSH original en inglés — ver `condLabel()`.
     - texto libre de AEMPS (castellano) y de openFDA (inglés) se muestra tal
       cual salió de la fuente, con el atributo `lang` correspondiente y, si
       no coincide con el idioma elegido, una etiqueta chica que lo aclara.

   `T` sólo tiene los textos que arma esta interfaz: labels, botones, ayudas,
   mensajes de estado y las plantillas de las tarjetas de hallazgo. */

const T = {
  es: {
    page_title: "Consilio — Seguridad en la prescripción",
    tagline: "Seguridad en la prescripción",
    lang_switch_label: "Idioma de la interfaz",

    btn_ejemplo: "Probar un ejemplo",
    btn_ejemplo_title: "Carga una receta de ejemplo con interacciones conocidas",
    btn_ayuda: "¿Qué evalúa?",

    ayuda_cruza_h: "Qué cruza",
    ayuda_cruza_1_t: "Medicamento con medicamento",
    ayuda_cruza_1_d: "— todas las combinaciones posibles de la receta.",
    ayuda_cruza_2_t: "Medicamento con paciente",
    ayuda_cruza_2_d: "— embarazo y semana de gestación, lactancia, función renal y hepática, alergias declaradas, patologías por código CIE-10, y criterios de prescripción en el anciano a partir de los 65 años.",

    ayuda_gravedad_h: "Cómo leer la gravedad",
    ayuda_grave_t: "Grave",
    ayuda_grave_d: "— evitar la combinación o suspender uno de los dos.",
    ayuda_moderada_t: "Moderada",
    ayuda_moderada_d: "— valorar beneficio/riesgo y monitorizar.",
    ayuda_leve_t: "Leve",
    ayuda_leve_d: "— relevancia clínica limitada.",
    ayuda_revisar_t: "Revisar",
    ayuda_revisar_d: "— la fuente registra el par pero no lo gradúa: consultar el prospecto.",

    ayuda_no_h: "Qué NO hace",
    ayuda_no_1_pre: "No controla",
    ayuda_no_1_b: "dosis",
    ayuda_no_1_post: "ni duración del tratamiento.",
    ayuda_no_2_pre: "No evalúa",
    ayuda_no_2_b: "peso, talla ni función renal por aclaramiento",
    ayuda_no_2_post: ": la función renal entra como alterada/normal.",
    ayuda_no_3_pre: "No detecta",
    ayuda_no_3_b: "reactividad cruzada",
    ayuda_no_3_post: "entre alergias: sólo el fármaco exacto declarado.",
    ayuda_no_4: "No asume simultaneidad parcial: cruza todo contra todo.",
    ayuda_no_5_b: "No decide.",
    ayuda_no_5_post: "Avisa y deja constancia.",

    card_meds_h: "Medicamentos a verificar",
    card_meds_hint: "Escribí el nombre del principio activo. Agregá dos o más para consultar interacciones entre ellos.",
    q_placeholder: "warfarina, ibuprofeno, sildenafil…",
    q_aria: "Buscar medicamento",

    card_perfil_h: "Perfil del paciente",
    card_perfil_opt: "opcional",

    label_sexo: "Sexo",
    opt_sexo_vacio: "—",
    opt_sexo_f: "Femenino",
    opt_sexo_m: "Masculino",
    label_edad: "Edad",
    edad_placeholder: "años",
    aviso_edad: "Desde los 65 se aplican los criterios de prescripción en el anciano.",

    check_embarazo: "Embarazo",
    check_lactancia: "Lactancia",
    semanas_aria: "Semana de gestación",
    semana_placeholder: "semana —",
    semana_n: "semana {n}",

    label_renal: "Función renal",
    opt_renal_normal: "normal",
    opt_renal_leve: "alterada — leve",
    opt_renal_moderada: "alterada — moderada",
    opt_renal_grave: "alterada — grave",
    label_hepatica: "Función hepática",
    opt_hepatica_normal: "normal",
    opt_hepatica_alterada: "alterada",

    label_alergias: "Alergias a medicamentos",
    qa_placeholder: "penicilina, aspirina…",
    aviso_alergias: "Se compara sólo el fármaco exacto. No se infiere reactividad cruzada por clase.",

    label_patologias: "Patologías",
    opt_patologias: "código CIE-10 o nombre",
    qp_placeholder: "N18, insuficiencia renal, K70…",
    aviso_patologias: "Se ofrecen sólo los códigos que disparan alguna alerta. Un código más específico que el de la lista (N18.5 contra N18) también se resuelve.",

    btn_consultar: "Consultar",
    btn_consultando: "Consultando…",
    kbd_hint_o: "o",
    btn_vaciar: "Vaciar todo",

    filtro_gravedad: "Gravedad",
    filtro_fuente: "Fuente",
    filtro_filtrar: "Filtrar",
    filtro_con_texto: "Sólo con explicación",
    filtro_sin_inferidas: "Ocultar inferidas de texto",
    filtro_buscar: "Buscar en resultados",
    filtro_texto_placeholder: "hemorragia, potasio, warfarina…",
    btn_quitar_filtros: "Quitar filtros",
    btn_copiar: "Copiar resumen",
    btn_copiar_title: "Copia el resumen al portapapeles",
    btn_imprimir: "Imprimir",

    disclaimer_1: "Información generada automáticamente a partir de fuentes públicas.",
    disclaimer_2: "No sustituye el criterio clínico.",
    disclaimer_3: "Verificar con el prospecto oficial ante cualquier duda.",

    sev_major: "Grave",
    sev_moderate: "Moderada",
    sev_minor: "Leve",
    sev_unknown: "Revisar",

    fuente_aemps: "AEMPS — Agencia Española de Medicamentos",
    fuente_ddinter: "DDInter 2.0 — base curada de interacciones",
    fuente_openfda: "openFDA — prospecto oficial de la FDA",
    fuente_medrt: "MED-RT — Biblioteca Nacional de Medicina (EE.UU.)",
    fuente_recetalia: "Revisión propia de Consilio",
    fuente_consilio: "Regla propia de Consilio",
    fuente_perfil: "Dato cargado en el perfil del paciente",

    fuente_corta_aemps: "AEMPS",
    fuente_corta_ddinter: "DDInter",
    fuente_corta_openfda: "openFDA",
    fuente_corta_medrt: "MED-RT",
    fuente_corta_recetalia: "Consilio",
    fuente_corta_consilio: "Consilio",
    fuente_corta_perfil: "Perfil",

    toast_error_servicio: "No se pudo consultar el servicio.",
    toast_ejemplo_error: "No se pudo cargar el ejemplo.",
    toast_falta_key: "El servicio está mal configurado: falta la API key del servidor.",
    prompt_api_key: "Este servicio requiere API key:",
    toast_key_guardada: "Guardada. Probá de nuevo.",
    toast_rate_limit: "Demasiadas consultas seguidas. Esperá unos segundos.",
    toast_error_http: "Error del servicio ({status}).",
    toast_copiado: "Resumen copiado al portapapeles.",
    toast_no_copiado: "El navegador no permitió copiar. Usá Imprimir.",
    error_sin_contacto: "No se pudo contactar al servicio.",

    err_desc_401: "El servicio pidió una API key.",
    err_desc_429: "Demasiadas consultas seguidas.",
    err_desc_503: "El servicio no está disponible.",
    err_desc_generico: "El servicio respondió con un error {status}.",

    n_medicamento: "medicamento",
    n_medicamentos: "medicamentos",
    n_dato: "dato",
    n_datos: "datos",
    n_combinacion: "combinación",
    n_combinaciones: "combinaciones",
    resumen_cruce_multi: "Se van a cruzar <strong>{pares}</strong> {palabra} entre sí, y cada medicamento contra el perfil del paciente.",
    resumen_cruce_uno: "Con un solo medicamento no hay combinaciones que cruzar. Agregá otro, o completá el perfil para cruzarlo contra el paciente.",

    col_title_inter: "Alertas medicamento — medicamento",
    col_title_contra: "Alertas medicamento — paciente",

    empty_sin_filtros: "Ningún hallazgo coincide con los filtros.",
    empty_sin_combinacion: "{sin} {palabra} sin interacción documentada.",
    empty_sin_combinacion_nota: "Que no hayamos encontrado una interacción documentada no significa que no exista.",
    empty_no_identificado_dup_pre: "no se pudo identificar, así que no se evaluó su duplicidad.",
    empty_no_identificado_alergia_pre: "No se pudo identificar",
    empty_no_identificado_alergia_post: "como medicamento, así que esa alergia no se tuvo en cuenta.",
    empty_no_evaluado: "no se pudo evaluar: {motivo}.",
    empty_sin_alertas_perfil_t: "Sin alertas para este perfil.",
    empty_sin_alertas_perfil_d: "Se evalúan embarazo y semana de gestación, lactancia, función renal y hepática, alergias declaradas, patologías por CIE-10 y, desde los 65 años, los criterios de prescripción en el anciano.",
    empty_agregar_meds: "Agregá dos o más medicamentos para cruzarlos entre sí.",
    empty_completar_perfil: "Completá el perfil del paciente para cruzarlo contra los medicamentos.",

    error_titulo_inter: "No se pudieron evaluar las interacciones",
    error_titulo_contra: "No se pudieron evaluar las alertas contra el paciente",
    error_detalle_post: "Los resultados de esta columna están incompletos: <strong>no interpretar el vacío como ausencia de alertas.</strong>",
    btn_reintentar: "Reintentar",

    filtro_estado: "{n} {palabra} por los filtros.",
    n_hallazgo_oculto: "hallazgo oculto",
    n_hallazgos_ocultos: "hallazgos ocultos",

    fuentes_consultadas: "Fuentes consultadas: {lista}.",
    cov_de: "de",

    tag_inferida: "inferida de texto",
    tag_clase: "regla de clase",
    evidence_sin_gravedad: "Interacción registrada sin gravedad asignada: revisar el prospecto.",
    evidence_sin_descripcion: "La fuente registra el par y su gravedad, pero no aporta descripción del mecanismo.",
    manejo_label: "Qué hacer:",
    gravedad_segun: "· gravedad según {fuente}",

    dup_titulo_sustancia: "Misma sustancia en dos productos",
    dup_titulo_clase: "Duplicidad de clase:",
    dup_badge_no_alertada: "No alertada",
    dup_badge_duplicidad: "Duplicidad",
    dup_detalle_sustancia: "{sust} aparece en {n} productos distintos.",
    dup_detalle_clase: "{n} productos de la misma clase ({sust}){cupo}",
    dup_cupo: "; el máximo sin alerta es {cupo}",
    dup_motivo_label: "Por qué no se alertó:",
    dup_pendiente_validacion: "— excepción pendiente de validación farmacéutica.",
    dup_tambien_en: "También en:",
    dup_grupo: "grupo",
    sup_duplicidad_1: "duplicidad no alertada",
    sup_duplicidad_n: "duplicidades no alertadas",
    sup_por_excepcion: "por una excepción curada",

    badge_contraindicado: "Contraindicado",
    badge_precaucion: "Precaución",

    badge_verificar_65: "Verificar — mayor de 65",
    badge_evitar_65: "Evitar — mayor de 65",
    geriatrica_aplica_si: "Aplica si:",
    geriatrica_meta: "— criterios de prescripción en el anciano",

    badge_alergia: "Alergia declarada",
    alergia_evidencia_pre: "El paciente declaró alergia a",
    alergia_evidencia_post: "que es este mismo fármaco.",
    alergia_meta: "Perfil del paciente",

    nota_texto_ingles: "Texto original del prospecto, en inglés.",
    nota_texto_espanol: "Texto original en castellano (AEMPS).",

    copia_titulo: "CONSILIO — consulta de seguridad en la prescripción",
    copia_medicamentos: "Medicamentos: {lista}",
    copia_paciente: "Paciente: {datos}",
    copia_sin_datos: "sin datos",
    copia_sin_meds: "—",
    copia_sexo: "sexo {sexo}",
    copia_anios: "{edad} años",
    copia_embarazo_semana: "embarazo semana {n}",
    copia_embarazo: "embarazo",
    copia_lactancia: "lactancia",
    copia_renal: "función renal {v}",
    copia_hepatica: "función hepática {v}",
    copia_alergias: "alergias: {lista}",
    copia_patologias: "patologías: {lista}",
    copia_qhacer: "Qué hacer: {texto}",
    copia_fuente: "Fuente: {fuente}",
    copia_dup: "[DUPLICIDAD] {que}: {sust}",
    copia_dup_sustancia: "misma sustancia",
    copia_contraindicado: "[CONTRAINDICADO] {drug} — {cond}",
    copia_precaucion: "[PRECAUCIÓN] {drug} — {cond}",
    copia_verificar: "VERIFICAR",
    copia_evitar: "EVITAR",
    locale: "es-UY",

    alerta_1: "alerta",
    alerta_n: "alertas",
  },

  en: {
    page_title: "Consilio — Prescription safety",
    tagline: "Prescription safety",
    lang_switch_label: "Interface language",

    btn_ejemplo: "Try an example",
    btn_ejemplo_title: "Loads a sample prescription with known interactions",
    btn_ayuda: "What does it check?",

    ayuda_cruza_h: "What it cross-checks",
    ayuda_cruza_1_t: "Drug with drug",
    ayuda_cruza_1_d: "— every possible combination in the prescription.",
    ayuda_cruza_2_t: "Drug with patient",
    ayuda_cruza_2_d: "— pregnancy and gestational week, breastfeeding, kidney and liver function, declared allergies, conditions by ICD-10 code, and prescribing criteria for the elderly from age 65.",

    ayuda_gravedad_h: "How to read severity",
    ayuda_grave_t: "Severe",
    ayuda_grave_d: "— avoid the combination or discontinue one of the two.",
    ayuda_moderada_t: "Moderate",
    ayuda_moderada_d: "— weigh benefit/risk and monitor.",
    ayuda_leve_t: "Minor",
    ayuda_leve_d: "— limited clinical relevance.",
    ayuda_revisar_t: "Review",
    ayuda_revisar_d: "— the source records the pair but doesn't grade it: check the label.",

    ayuda_no_h: "What it does NOT do",
    ayuda_no_1_pre: "It does not check",
    ayuda_no_1_b: "dose",
    ayuda_no_1_post: "or treatment duration.",
    ayuda_no_2_pre: "It does not assess",
    ayuda_no_2_b: "weight, height, or kidney function by clearance",
    ayuda_no_2_post: ": kidney function is entered as impaired/normal.",
    ayuda_no_3_pre: "It does not detect",
    ayuda_no_3_b: "cross-reactivity",
    ayuda_no_3_post: "between allergies: only the exact drug declared.",
    ayuda_no_4: "It does not assume partial overlap in time: it cross-checks everything against everything.",
    ayuda_no_5_b: "It does not decide.",
    ayuda_no_5_post: "It warns and leaves a record.",

    card_meds_h: "Drugs to check",
    card_meds_hint: "Type the active substance name. Add two or more to check interactions between them.",
    q_placeholder: "warfarin, ibuprofen, sildenafil…",
    q_aria: "Search drug",

    card_perfil_h: "Patient profile",
    card_perfil_opt: "optional",

    label_sexo: "Sex",
    opt_sexo_vacio: "—",
    opt_sexo_f: "Female",
    opt_sexo_m: "Male",
    label_edad: "Age",
    edad_placeholder: "years",
    aviso_edad: "From age 65, prescribing criteria for the elderly apply.",

    check_embarazo: "Pregnancy",
    check_lactancia: "Breastfeeding",
    semanas_aria: "Gestational week",
    semana_placeholder: "week —",
    semana_n: "week {n}",

    label_renal: "Kidney function",
    opt_renal_normal: "normal",
    opt_renal_leve: "impaired — mild",
    opt_renal_moderada: "impaired — moderate",
    opt_renal_grave: "impaired — severe",
    label_hepatica: "Liver function",
    opt_hepatica_normal: "normal",
    opt_hepatica_alterada: "impaired",

    label_alergias: "Drug allergies",
    qa_placeholder: "penicillin, aspirin…",
    aviso_alergias: "Only the exact drug is compared. Cross-reactivity by class is not inferred.",

    label_patologias: "Conditions",
    opt_patologias: "ICD-10 code or name",
    qp_placeholder: "N18, kidney failure, K70…",
    aviso_patologias: "Only codes that trigger an alert are offered. A code more specific than the listed one (N18.5 vs. N18) also resolves.",

    btn_consultar: "Check",
    btn_consultando: "Checking…",
    kbd_hint_o: "or",
    btn_vaciar: "Clear all",

    filtro_gravedad: "Severity",
    filtro_fuente: "Source",
    filtro_filtrar: "Filter",
    filtro_con_texto: "Only with explanation",
    filtro_sin_inferidas: "Hide inferred from text",
    filtro_buscar: "Search in results",
    filtro_texto_placeholder: "bleeding, potassium, warfarin…",
    btn_quitar_filtros: "Clear filters",
    btn_copiar: "Copy summary",
    btn_copiar_title: "Copies the summary to the clipboard",
    btn_imprimir: "Print",

    disclaimer_1: "Information generated automatically from public sources.",
    disclaimer_2: "It does not replace clinical judgment.",
    disclaimer_3: "Verify with the official label if in doubt.",

    sev_major: "Severe",
    sev_moderate: "Moderate",
    sev_minor: "Minor",
    sev_unknown: "Review",

    fuente_aemps: "AEMPS — Spanish Agency of Medicines and Health Products",
    fuente_ddinter: "DDInter 2.0 — curated interaction database",
    fuente_openfda: "openFDA — official FDA drug label",
    fuente_medrt: "MED-RT — U.S. National Library of Medicine",
    fuente_recetalia: "Consilio's own review",
    fuente_consilio: "Consilio's own rule",
    fuente_perfil: "Data entered in the patient profile",

    fuente_corta_aemps: "AEMPS",
    fuente_corta_ddinter: "DDInter",
    fuente_corta_openfda: "openFDA",
    fuente_corta_medrt: "MED-RT",
    fuente_corta_recetalia: "Consilio",
    fuente_corta_consilio: "Consilio",
    fuente_corta_perfil: "Profile",

    toast_error_servicio: "Could not reach the service.",
    toast_ejemplo_error: "Could not load the example.",
    toast_falta_key: "The service is misconfigured: the server API key is missing.",
    prompt_api_key: "This service requires an API key:",
    toast_key_guardada: "Saved. Try again.",
    toast_rate_limit: "Too many requests in a row. Wait a few seconds.",
    toast_error_http: "Service error ({status}).",
    toast_copiado: "Summary copied to the clipboard.",
    toast_no_copiado: "The browser didn't allow copying. Use Print.",
    error_sin_contacto: "Could not reach the service.",

    err_desc_401: "The service asked for an API key.",
    err_desc_429: "Too many requests in a row.",
    err_desc_503: "The service is unavailable.",
    err_desc_generico: "The service responded with a {status} error.",

    n_medicamento: "drug",
    n_medicamentos: "drugs",
    n_dato: "field",
    n_datos: "fields",
    n_combinacion: "combination",
    n_combinaciones: "combinations",
    resumen_cruce_multi: "<strong>{pares}</strong> {palabra} will be cross-checked with each other, and each drug against the patient profile.",
    resumen_cruce_uno: "With a single drug there are no combinations to cross-check. Add another, or complete the profile to check it against the patient.",

    col_title_inter: "Drug — drug alerts",
    col_title_contra: "Drug — patient alerts",

    empty_sin_filtros: "No finding matches the filters.",
    empty_sin_combinacion: "{sin} {palabra} without a documented interaction.",
    empty_sin_combinacion_nota: "Not finding a documented interaction doesn't mean one doesn't exist.",
    empty_no_identificado_dup_pre: "could not be identified, so its duplication wasn't evaluated.",
    empty_no_identificado_alergia_pre: "Could not identify",
    empty_no_identificado_alergia_post: "as a drug, so that allergy wasn't taken into account.",
    empty_no_evaluado: "could not be evaluated: {motivo}.",
    empty_sin_alertas_perfil_t: "No alerts for this profile.",
    empty_sin_alertas_perfil_d: "We evaluate pregnancy and gestational week, breastfeeding, kidney and liver function, declared allergies, conditions by ICD-10, and, from age 65, prescribing criteria for the elderly.",
    empty_agregar_meds: "Add two or more drugs to cross-check them against each other.",
    empty_completar_perfil: "Complete the patient profile to cross-check it against the drugs.",

    error_titulo_inter: "Interactions could not be evaluated",
    error_titulo_contra: "Alerts against the patient could not be evaluated",
    error_detalle_post: "The results in this column are incomplete: <strong>do not read the empty state as an absence of alerts.</strong>",
    btn_reintentar: "Retry",

    filtro_estado: "{n} {palabra} by the filters.",
    n_hallazgo_oculto: "finding hidden",
    n_hallazgos_ocultos: "findings hidden",

    fuentes_consultadas: "Sources consulted: {lista}.",
    cov_de: "of",

    tag_inferida: "inferred from text",
    tag_clase: "class rule",
    evidence_sin_gravedad: "Interaction recorded without an assigned severity: check the label.",
    evidence_sin_descripcion: "The source records the pair and its severity, but provides no description of the mechanism.",
    manejo_label: "What to do:",
    gravedad_segun: "· severity per {fuente}",

    dup_titulo_sustancia: "Same substance in two products",
    dup_titulo_clase: "Class duplication:",
    dup_badge_no_alertada: "Not flagged",
    dup_badge_duplicidad: "Duplication",
    dup_detalle_sustancia: "{sust} appears in {n} different products.",
    dup_detalle_clase: "{n} products in the same class ({sust}){cupo}",
    dup_cupo: "; the maximum without an alert is {cupo}",
    dup_motivo_label: "Why it wasn't flagged:",
    dup_pendiente_validacion: "— exception pending pharmaceutical validation.",
    dup_tambien_en: "Also in:",
    dup_grupo: "group",
    sup_duplicidad_1: "duplication not flagged",
    sup_duplicidad_n: "duplications not flagged",
    sup_por_excepcion: "due to a curated exception",

    badge_contraindicado: "Contraindicated",
    badge_precaucion: "Precaution",

    badge_verificar_65: "Check — over 65",
    badge_evitar_65: "Avoid — over 65",
    geriatrica_aplica_si: "Applies if:",
    geriatrica_meta: "— prescribing criteria for the elderly",

    badge_alergia: "Declared allergy",
    alergia_evidencia_pre: "The patient declared an allergy to",
    alergia_evidencia_post: "which is this same drug.",
    alergia_meta: "Patient profile",

    nota_texto_ingles: "Original text from the FDA label, in English.",
    nota_texto_espanol: "Original text in Spanish (AEMPS).",

    copia_titulo: "CONSILIO — prescription safety check",
    copia_medicamentos: "Drugs: {lista}",
    copia_paciente: "Patient: {datos}",
    copia_sin_datos: "no data",
    copia_sin_meds: "—",
    copia_sexo: "sex {sexo}",
    copia_anios: "{edad} years old",
    copia_embarazo_semana: "pregnancy week {n}",
    copia_embarazo: "pregnancy",
    copia_lactancia: "breastfeeding",
    copia_renal: "kidney function {v}",
    copia_hepatica: "liver function {v}",
    copia_alergias: "allergies: {lista}",
    copia_patologias: "conditions: {lista}",
    copia_qhacer: "What to do: {texto}",
    copia_fuente: "Source: {fuente}",
    copia_dup: "[DUPLICATION] {que}: {sust}",
    copia_dup_sustancia: "same substance",
    copia_contraindicado: "[CONTRAINDICATED] {drug} — {cond}",
    copia_precaucion: "[PRECAUTION] {drug} — {cond}",
    copia_verificar: "CHECK",
    copia_evitar: "AVOID",
    locale: "en-US",

    alerta_1: "alert",
    alerta_n: "alerts",
  },
};

function getLang() {
  return localStorage.getItem("consilio_lang") === "en" ? "en" : "es";
}

let LANG = getLang();

function t(key, vars) {
  let s = (T[LANG] && T[LANG][key] !== undefined) ? T[LANG][key] : T.es[key];
  if (s === undefined) return key;
  if (vars) {
    Object.entries(vars).forEach(([k, v]) => {
      s = s.replaceAll(`{${k}}`, v);
    });
  }
  return s;
}

function applyStaticI18n() {
  document.documentElement.lang = LANG;
  document.title = t("page_title");
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.getAttribute("data-i18n-html"));
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.getAttribute("data-i18n-title"));
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
    el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria-label")));
  });
  document.querySelectorAll("#lang-switch button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));
}

// `onLangChange` la define app.js: redibuja píldoras y, si hay resultados,
// vuelve a armar filtros y tarjetas. Acá no se sabe nada de ese estado.
function setLang(lang) {
  const next = lang === "en" ? "en" : "es";
  if (next === LANG) return;
  LANG = next;
  localStorage.setItem("consilio_lang", LANG);
  applyStaticI18n();
  if (typeof onLangChange === "function") onLangChange();
}

document.querySelectorAll("#lang-switch button").forEach((b) =>
  b.addEventListener("click", () => setLang(b.dataset.lang)));

// Este script va al final del body, después de todo el HTML: el DOM ya está
// armado, así que se aplica de una, igual que `syncButtons()` en app.js.
applyStaticI18n();
