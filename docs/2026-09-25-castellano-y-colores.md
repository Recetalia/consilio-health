# Castellano de fuente oficial, búsqueda multilingüe y colores de alerta — diseño y plan

Fecha: 2026-09-25 · Estado: aprobado por Pablo ("sólo fuentes oficiales")

## Por qué

Pedido de Pablo sobre la UI desplegada: las alertas se confunden con el verde de la página, y
"está todo en inglés" (captura: la píldora decía `Nitroglycerin`, la tarjeta "sin graduar" era
gris). Decisión: **sólo fuentes oficiales**, nada de traducción automática.

## Medido (2026-09-25, base real)

- 1.939 fármacos; **725** con nombre en castellano (65 alias `lang='es'` + DNMA). **1.214 sin**.
- Cruzando por esqueleto INN contra `DICCIONARIO_ATC.xml` (N5) de la AEMPS: **779** de esos 1.214
  consiguen nombre oficial (Acarbose→Acarbosa, Acenocoumarol→Acenocumarol). Falta sumar
  `DICCIONARIO_PRINCIPIOS_ACTIVOS.xml` (tag `<principioactivo>`, en MAYÚSCULAS).
- 4.433 interacciones de openFDA con texto en inglés: **se quedan en inglés** (no hay fuente
  oficial en castellano), con el aviso "Texto original del prospecto, en inglés".
- 1.517 patologías MeSH en inglés; 144 traducidas a mano en `app/web/condiciones-es.js`. La
  fuente oficial es **DeCS** (BIREME/OPS/OMS): gratis pero exige licencia por formulario
  (<https://decs.bvsalud.org/en/for-developers/>). La copia en UMLS (MSHSPA) es nivel 3: no sirve
  para producción. → bloqueado por un trámite de Pablo.

## Diseño

1. **Nombres oficiales.** `scripts/enrich_nombres_aemps.py` carga alias `lang='es'`,
   `source='aemps'` desde los dos diccionarios, por match de esqueleto con el canónico:
   - sólo si el nombre AEMPS no tiene tokens de ≤2 caracteres (misma regla que la resolución:
     "Vitamina A" y "Vitamina E" colapsan) y el match es **único en los dos sentidos**;
   - las variantes con vía entre paréntesis (`Diclofenac (topical)`) reciben el nombre con la vía
     traducida por un diccionario cerrado (topical→tópico, ophthalmic→oftálmico, …). No se
     inventa: si la vía no está en el diccionario, la variante no recibe nombre;
   - re-sembrable (`delete ... where source='aemps' and lang='es'`), deja registro en `meta`.
2. **Precedencia del nombre a mostrar**: alias `es` curado a mano (el que ya existía, `source`
   ≠ 'aemps') > DNMA (grafía del vademécum uruguayo) > AEMPS.
3. **Búsqueda multilingüe**: `search_drugs` ya busca en todos los alias; con los `es` de la AEMPS
   "amlodipino"/"nitroglicerina" aparecen. Se suma el DNMA como fuente de búsqueda (hoy sólo de
   display) para las grafías locales.
4. **Colores**: `unknown` deja de ser gris → **violeta, etiqueta "Revisar"**. Rojo (grave) y ámbar
   (moderada) se mantienen; ninguna tarjeta de alerta usa tonos del verde de la marca.

## Plan (dos flujos en paralelo)

- **Backend** (árbol principal): ETL + tests de regresión (Acarbose→Acarbosa, Nitroglycerin→
  Nitroglicerina, variante tópica, colisión de vitaminas no asigna) + precedencia + búsqueda por
  DNMA + tests de `search_drugs` en castellano e inglés. Correr el ETL sobre la base.
- **UI** (worktree): violeta "Revisar"; revisar que ningún texto estático de la UI quede en inglés;
  que el botón "Probar un ejemplo" pueble los nombres en castellano.
- **Integración y deploy**: merge, suite, `eval_duplicidad.py`, verificación en Chrome, deploy al
  `.98` (procedimiento en `2026-09-24-duplicidad-terapeutica-design.md` § Despliegue).
