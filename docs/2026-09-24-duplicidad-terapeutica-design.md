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
- Clase = grupo AEMPS, identificado por su `atc_a` ancla; `desc` es su nombre.
  Miembros = expansión de `atc_a` ∪ expansión de cada `atc_b` del grupo.
  Expansión: N5 → molécula por nombre; N3/N4 → prefijo sobre `drug.atc`.
  Los códigos de combinado (p. ej. `C09BA`) no mapean a sustancias sueltas y se
  ignoran: el combinado entra a la clase por sus ingredientes.
- Al chequear: por clase, contar **productos distintos** con algún miembro. Si
  supera el cupo (default 1) → alerta, severidad moderada.
- Si todos los productos de la alerta de clase ya están cubiertos por una alerta
  de capa 1 de la misma sustancia, la de clase no se emite (no duplicar el aviso).

### Capa 3 — cupos y excepciones curados
`data/duplicidad_cupos.json`, en git, curado a mano. Por clase:

```json
{ "B01AC": { "cupo": 2, "motivo": "doble antiagregación post-stent",
             "referencia": "ESC 2023 SCA" },
  "J01C":  { "desactivada": true, "motivo": "grupo demasiado amplio: ..." } }
```

Y excepciones por grupos de sustancias dentro de una clase, bajo la clave
`"excepciones"`: `{ "clase": "A10A", "grupos": [["insulina glargina", ...],
["insulina aspart", ...]], "motivo": "basal + bolo" }` — un producto de cada grupo
no cuenta como duplicidad; dos del mismo grupo sí.
Una alerta suprimida por cupo/excepción va a `duplicities_suppressed` con el
`motivo` y la `referencia`.

**Primer lote**: el de `cerrar-los-rojos.md:255-257` más lo que salga de revisar
los 144 grupos. ⚠️ Lo valida alguien con criterio farmacéutico antes de
producción; hasta entonces el JSON lleva `"validado": false` por entrada.

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
"duplicity_not_evaluated": ["sustancia sin clase"]
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
ibuprofeno + diclofenaco → clase; diazepam + lorazepam → clase; enalapril +
amlodipino + hidroclorotiazida → nada; AAS + clopidogrel → suprimida (cupo 2);
insulina glargina + aspart → suprimida. Un script imprime aciertos/fallos por
capa: es la primera métrica que va a correr la routine semanal.

## Errores

Sustancia no resuelta → `duplicity_not_evaluated`, nunca se omite en silencio.
Base sin `drug_class` (ETL no corrido) → `duplicities` vacío más un aviso en
`coverage_summary`, no 500.
