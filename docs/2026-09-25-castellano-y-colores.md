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
- **2026-09-25, dry-run real de `scripts/enrich_nombres_aemps.py --dry-run`** (N5 del ATC +
  `DICCIONARIO_PRINCIPIOS_ACTIVOS.xml`, con las tres reglas de descarte — combinación, token
  ≤2 caracteres, ambigüedad en los dos sentidos — y el filtro de PK `(drug_id, alias_norm)`
  aplicados): **594** de los 1.214 sin nombre lo ganan (725 → 1.319 con nombre, 65,3% de 1.939).
  Quedan **620** sin nombre. La primera cifra de 779 era una medición preliminar (sólo ATC N5,
  sin las tres reglas de descarte completas); el número final y correcto es este.
  De los 1.483 matches que produce el emparejamiento, 457 no generan fila nueva porque el
  fármaco ya tenía un alias (casi siempre en inglés) cuyo `alias_norm` coincide exactamente con
  el nombre en castellano asignado (`Misoprostol`, `Ondansetron`, `Sorbitol`, …: mismo
  significante en los dos idiomas) — la restricción es la propia PK de `drug_alias`
  `(drug_id, alias_norm)`, no una regla de negocio nueva.
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

## DDInter: las 6 categorías que faltaban

**Hallazgo (2026-09-25).** `scripts/ddinter_sources.py` decía que las categorías ATC C/G/J/M/N/S
"no están disponibles" y cargaba sólo A B D H L P R V. Era falso. Cómo se midió:
`curl` a `https://ddinter2.scbdd.com/static/media/download/ddinter_downloads_code_{C,G,J,M,N,S}.csv`
devuelve 200 con el mismo formato (`DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level`), y C tiene
60.455 líneas y N 91.596. Sin ellas, pares graves clásicos llegaban sólo desde openFDA como
`unknown`: tramadol + fluoxetina, amiodarona + digoxina y sildenafilo + nitroglicerina.

**Por qué no hubo re-seed.** `build_recetalia_db seed --force` borra la base y numera los `drug_id`
por `ddinter_id` ordenado. Los 32 fármacos nuevos habrían corrido los ids y roto `drug_class`,
`drug_alias`, `dnma_substance_map`, las alertas y los pares AEMPS/openFDA. Por eso se agregó
`build_recetalia_db extend`: suma al final los fármacos y pares nuevos y no toca lo que ya existe.

**Números** (`select source, severity, count(*) from interaction group by 1,2`):

| fuente | gravedad | antes | después |
|---|---|---:|---:|
| ddinter | major | 26.914 | 39.082 |
| ddinter | moderate | 96.675 | 143.748 |
| ddinter | minor | 6.833 | 9.736 |
| ddinter | unknown | 29.813 | 42.415 |
| aemps | major / moderate | 435 / 1.386 | 435 / 1.386 |
| openfda | major / moderate / unknown | 775 / 1.270 / 2.388 | igual |

- `ddinter.db`: 160.235 → 234.981 pares. Ningún par viejo cambió de gravedad ni se perdió, y no
  hubo conflictos de gravedad entre CSV.
- Fármacos: 1.939 → 1.971. Los 1.939 ids previos y las 166.489 filas de `interaction` previas
  quedaron idénticos (comparado con `attach` contra el backup).
- Las 2.388 openFDA `unknown`: **1.337** tienen ahora par DDInter con gravedad (540 major,
  703 moderate, 94 minor), y otras 137 lo tienen como `unknown` en DDInter.
- `drug_class` 661 → 662, alertas geriátricas 166 = 166, alias AEMPS 967 → 981.

**Bug de paso.** `enrich_nombres_aemps` no era idempotente: sus propias filas contaban como "ya
existentes", así que una segunda corrida borraba las 967 y escribía sólo las nuevas (quedaron 14).
Corregido, y hay un test que lo cubre.

**Comando** (orden y tiempos medidos):

```bash
python -m scripts.build_ddinter_db fetch        # o curl de los 6 CSV nuevos
python -m scripts.build_ddinter_db resolve-rxnorm --previous <crosswalk anterior>   # 2 min, 102 nombres
python -m scripts.build_ddinter_db build --tag ddinter-2026-09-25
python -m scripts.build_recetalia_db extend     # +32 fármacos, +74.746 pares
python scripts/fetch_drug_atc.py                # 2 min 14 s
python -m scripts.enrich_drug_aliases           # 27 min: recorre los 1.891 con RxCUI, no sólo los nuevos
PYTHONPATH=scripts python scripts/cross_aemps_interactions.py
PYTHONPATH=scripts python scripts/cross_aemps_geriatria.py
PYTHONPATH=scripts python scripts/cross_aemps_duplicidad.py
python -m scripts.enrich_nombres_aemps
```

**Pendiente.** Para los 32 fármacos nuevos no se corrieron openFDA (`fetch_openfda_labels`,
`derive_openfda_interactions`, `expand_class_interactions`) ni MED-RT: no tienen pares de
prospecto ni contraindicaciones por patología. MeSH y `condition_xref` no dependen de los
fármacos. La base nueva todavía no está desplegada en el `.98` ni en el `.217`.
