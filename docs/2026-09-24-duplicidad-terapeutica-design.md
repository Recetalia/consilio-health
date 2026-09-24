# Duplicidad terapéutica — diseño

Fecha: 2026-09-24 · Estado: aprobado el enfoque (B: clases con cupo), spec en revisión

## Objetivo

Alertar cuando una receta junta dos o más productos que hacen lo mismo, **sin**
alertar las combinaciones intencionales. Es el eje que VIDAL cubre y Consilio no
(`doc/2026-09-23-consilio-vs-vidal.md:109`).

La vara no es igualar a VIDAL sino superarlo en lo que no tiene:

- **Procedencia por hallazgo**: cada alerta dice qué regla la disparó y de qué
  fuente sale (grupo AEMPS, cupo curado por nosotros con su referencia).
- **Supresiones visibles**: lo que no se alertó por una excepción se devuelve
  aparte, con el motivo. El médico ve que el motor lo evaluó, no un silencio.
- **Lo no evaluable, declarado**: una sustancia sin clase resuelta sale como tal.

El número que ordena el diseño: el 80 % de las alertas de duplicidad se ignoran
y sólo el 4,1 % son clínicamente relevantes; un tercio eran combinaciones
intencionales (`doc/2026-09-23-consilio-cerrar-los-rojos.md:240`). El módulo vale
lo que valga su tasa de falsos positivos.

## Datos de partida (medidos 2026-09-24)

- `data/aemps/aemps_extra.json` → `duplicidades`: 1.593 reglas `{atc_a, atc_b, desc}`,
  144 `desc` distintos, 343 `atc_a` distintos. Sin cupo, sin recomendación.
  Niveles mezclados: `atc_a` 800 N5 / 715 N4 / 78 N3; `atc_b` 1.102 N5 / 478 N4 / 13 N3.
  Ningún script las lee hoy.
- `drug.atc`: 1.703/1.939 con ATC, **sólo nivel 4**, múltiple separado por coma.
  Los códigos N5 se resuelven por nombre (esqueleto + `DICCIONARIO_ATC.xml`),
  como ya hace `scripts/cross_aemps_interactions.py:8-35`.
- `/interactions` recibe `drugs: list[str]` plano. Recetalia descompone productos
  en sustancias y pierde la agrupación → la capa 1 es imposible con el contrato actual.

## Modelo: tres capas

### Capa 1 — misma sustancia en productos distintos
Si un mismo `drug_id` aparece en dos productos distintos → alerta, **cupo 0,
severidad alta**. Cubre el paracetamol dentro de un combinado y el AAS
multi-código, que ningún prefijo ATC ve. Sustancias del mismo producto nunca se
comparan entre sí (el médico no puede separarlas).

### Capa 2 — clase terapéutica con cupo
- **Clase = ATC4 del ancla** (`atc_a[:5]`; el código entero si es N3). Nombre de
  la clase: el del diccionario ATC de la AEMPS. Miembros = expansión de `atc_a`
  ∪ expansión de cada `atc_b` de las reglas de esa clase.
  Expansión: N5 → molécula por nombre; N3/N4 → prefijo sobre `drug.atc`.
- **Se descarta toda regla con un código de combinado** en cualquiera de sus
  lados, y al expandir por prefijo se ignoran los códigos de combinado que
  `drug.atc` trae por ingrediente.

  Qué es "código de combinado": N5 → `es_combinacion(nombre)`. N3/N4 → el
  nombre dice combinación (regex estricto, **sin** `inhibidores de`) **y** la
  mayoría de sus N5 hijos son combinaciones. Medido sobre los 629 códigos N3/N4
  de reglas + `drug.atc`: `es_combinacion` sola marca 197 (IBP, IECA monofármaco,
  insulinas, AINEs: falsos); sólo el criterio de hijos marca 60 con falsos como
  N02BE Anilidas (paracetamol). Los dos juntos dejan los combinados reales
  (C09BA/BB/DA/DB, C07BB/FB, C03EA/EB, G03AA, J01CR, N02AJ, M01BA…) y tres
  falsos (N04BA, B03BB, M03BB) que van a una lista explícita.

  Medido 2026-09-24 sobre la base real (script ad hoc con `Resolver`):
  - Agrupar por `desc` junta enalapril y amlodipino en "INHIBIDORES DE LA ECA Y
    BLOQUEANTES DE CANALES DE CALCIO" → IECA + ACA alertaría. Es el falso
    positivo canónico. Esos grupos están anclados en ATC de combinado.
  - Con `drug.atc` sin filtrar, la hidroclorotiazida entra a los ARA II vía
    `C09DX` (RxClass le asigna los ATC de los combinados que la contienen) →
    losartán + HCTZ alertaría.
  - Con clase por `desc` hay 143 grupos, 114 con ≥2 miembros; las reglas
    resuelven: clase 1.000 · molécula 757 · sin resolver 1.024 · sin-clase 284 ·
    ambiguo 57. La cifra con el modelo final la imprime el ETL.
  - Sin excepción alguna, IECA + ACA + tiazida queda en tres clases distintas
    (C09AA, C08CA, C03AA) y no alerta. AAS + clopidogrel tampoco: clopidogrel no
    está en ninguna regla de la AEMPS.
- Al chequear: por clase, contar **productos distintos** con algún miembro. Si
  supera el cupo (default 1) → alerta, severidad moderada.
- Si todos los productos de la alerta de clase ya están cubiertos por una alerta
  de capa 1 de la misma sustancia, la de clase no se emite (no duplicar el aviso).

### Capa 3 — cupos y excepciones curados
`data/duplicidad_cupos.json`, en git, curado a mano:

```json
{ "clases": {
    "<class_id>": { "cupo": 2, "motivo": "...", "referencia": "...", "validado": false },
    "<class_id>": { "desactivada": true, "motivo": "...", "validado": false } },
  "excepciones": [
    { "clase": "<class_id>", "grupos": [["<drug.canonical>", "..."], ["..."]],
      "motivo": "...", "referencia": "...", "validado": false } ] }
```

- `cupo`: cuántos productos distintos de la clase se permiten (default 1).
- `desactivada`: la clase no alerta nunca (grupo demasiado amplio).
- `excepciones`: dentro de la clase, un producto de cada grupo no cuenta como
  duplicidad; dos del mismo grupo sí. Los grupos van por `drug.canonical` para
  no depender de la resolución de nombres.

Una alerta suprimida por cupo, desactivación o excepción va a
`duplicities_suppressed` con `motivo` y `referencia`.

**Primer lote: vacío, y a propósito.** Con clase = ATC4 y los combinados
descartados, los casos de `cerrar-los-rojos.md:255-257` ya caen en clases
distintas (IECA/ACA/tiazida; LABA R03AC / LAMA R03BB; insulina rápida A10AB /
basal A10AE) o fuera de las reglas (AAS + clopidogrel). Poner un cupo 2 en B01AC
"por la doble antiagregación" suprimiría AAS + triflusal, que sí es duplicidad.
Cada entrada futura sale de un caso real que falle, y lleva `"validado": false`
hasta que la revise alguien con criterio farmacéutico.

### Resolución de nombres en castellano
Recetalia manda sustancias del DNMA, en castellano. Medido: `diclofenaco` no
resuelve por `drug_alias`; `amlodipino` sólo por `dnma_substance_map`. Sin
resolver no hay duplicidad posible (ni interacción). `drug_id_by_name` suma dos
respaldos, en orden: `dnma_substance_map` por nombre normalizado, y luego el
**esqueleto** INN castellano↔inglés de `cross_aemps_interactions.skeleton`,
aceptado sólo si apunta a un único fármaco. El esqueleto se mueve a
`app/nlp/nombres.py` y el script lo importa de ahí.

### Fuera de alcance (segunda vuelta)
Capa de mecanismo sobre RxClass (MoA/EPC): se decide con los casos de prueba en
mano, cuando muestren qué se escapa. Vía de administración (tópico vs sistémico):
el contrato la acepta desde ya como campo opcional, pero la regla se escribe
cuando Recetalia la mande.

## Contrato

`POST /interactions` — compatible hacia atrás:

```json
{ "drugs": ["..."],
  "products": [ { "id": "p1", "substances": ["paracetamol"] },
                { "id": "p2", "substances": ["paracetamol", "codeína"], "route": "oral" } ] }
```

Si viene sólo `drugs`, cada nombre es un producto. La respuesta suma:

```json
"duplicities": [ { "layer": "substance|class", "class_id": "N02BE", "class_desc": "...",
                   "products": ["p1","p2"], "substances": ["paracetamol"],
                   "count": 2, "cupo": 1, "severity": "major|moderate",
                   "source": "aemps|consilio", "rule": "N02BE" } ],
"duplicities_suppressed": [ { ...mismos campos, "motivo": "...", "referencia": "..." } ],
"duplicity_not_evaluated": ["sustancia no resuelta"],
"duplicity_warnings": ["la base no tiene clases cargadas"]
```

## Componentes

| Unidad | Responsabilidad |
|---|---|
| `scripts/cross_aemps_duplicidad.py` | Puebla `drug_class(drug_id, class_id, class_desc, source)` desde las reglas AEMPS. Re-sembrable (`DELETE ... WHERE source='aemps'`). Reusa la resolución de `cross_aemps_interactions.py`. |
| `RecetaliaDatabase.classes_for(drug_ids)` | Lectura de membresías. |
| `app/services/duplicity_checker.py` | Puro: productos resueltos + membresías + cupos → alertas / suprimidas. Sin I/O. |
| `interaction_checker.check` | Resuelve `products`, llama al checker, suma los campos. |
| `app/web/app.js` | `cardDuplicidad`, filtro, conteo, resumen al portapapeles; suprimidas plegadas. |
| Recetalia (`feat/consilio-interacciones`) | Mandar `products`; mapear `duplicities` a productos; arreglar el `putIfAbsent` que pierde el segundo producto de una sustancia repetida. |

## Calidad

`tests/regression/casos_duplicidad.json`: casos clínicos con esperado
(alerta / suprimida / nada). Mínimo: paracetamol + paracetamol/codeína → capa 1;
ibuprofeno + diclofenaco → clase; diazepam + lorazepam → clase; omeprazol + pantoprazol → clase; losartán + hidroclorotiazida → nada; enalapril +
amlodipino + hidroclorotiazida → nada; AAS + clopidogrel → nada;
sertralina + fluoxetina → clase; ranitidina + famotidina → clase (triflusal no está en la base). Un script imprime aciertos/fallos por
capa: es la primera métrica que va a correr la routine semanal.

## Errores

Sustancia no resuelta → `duplicity_not_evaluated`, nunca se omite en silencio.
Base sin `drug_class` (ETL no corrido) → `duplicities` vacío más un aviso en `duplicity_warnings`, no 500.
