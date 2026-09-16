# Consilio

**Seguridad en la prescripción.** Un servicio que revisa una lista de
medicamentos y devuelve las interacciones entre ellos, con su gravedad, la
evidencia que la respalda y de dónde salió.

Consilio **no bloquea**. Informa; el médico decide. Un sistema que frena se
aprende a esquivar; uno que aconseja se consulta.

---

## Lo que tiene adentro

| | |
|---|---|
| Interacciones fármaco-fármaco | 163.660 |
| Alertas fármaco-patología | 6.522 sobre 965 patologías |
| Fármacos en el catálogo de interacciones | 1.939 |
| Alias de búsqueda | 2.357 |

Cobertura del vademécum uruguayo (DNMA): **59,5 % de los 6.847 productos
comerciales** tiene todas sus sustancias mapeadas. Medido por sustancia da
52,7 % (733 de 1.390); sube al mirar productos porque las sustancias comunes
están en más marcas. Aparte, 657 productos (9,6 %) **no tienen sustancia
asociada en el propio DNMA** y son inevaluables por construcción.

Tres mecanismos de detección, y cada uno encuentra lo que los otros no:

1. **Base curada** — DDInter 2.0, 160.235 pares con severidad estructurada.
2. **Prospectos de la FDA** — 2.515 pares que la base curada no tiene, con la
   frase textual del prospecto como evidencia.
3. **Expansión por clase** — 455 pares que **ningún sistema por nombre puede
   encontrar**. Un prospecto que advierte sobre "inhibidores de la MAO" nunca
   nombra a la fenelzina; Consilio entiende la clase y la expande.

Ese tercero encontró *fenelzina + fluoxetina* (síndrome serotoninérgico) y
*sildenafil + nitratos* (hipotensión potencialmente fatal).

**Cuando no sabe, lo dice.** Lo que no puede evaluar sale marcado como no
evaluable, nunca como seguro.

---

## Correr local

```bash
uv sync                                   # sin torch: ver "El extra ml"
uv run python -m scripts.build_recetalia_db seed   # requiere data/ddinter.db
CONSILIO_ALLOW_NO_API_KEY=1 uv run uvicorn app.main:app --port 8100
```

- Interfaz de consulta: <http://localhost:8100/>
- OpenAPI: <http://localhost:8100/docs>

```bash
uv run pytest -q          # 110 tests
```

### La base de conocimiento no está en el repo

Se construye con el ETL y **se monta**, no se hornea en la imagen. Es una
decisión legal además de práctica: ver [Licencias](#licencias).

```bash
python -m scripts.build_ddinter_db fetch                  # CSV de DDInter
python -m scripts.build_ddinter_db resolve-rxnorm         # crosswalk RxNorm
python -m scripts.build_ddinter_db build --tag <tag>      # SQLite crudo
python -m scripts.build_recetalia_db seed                 # nuestro esquema
python -m scripts.fetch_openfda_labels                    # prospectos FDA
python -m scripts.derive_openfda_interactions             # pares por nombre
python -m scripts.expand_class_interactions               # pares por clase
python -m scripts.fetch_medrt_contraindications           # fármaco-patología
python -m scripts.enrich_drug_aliases                     # alias de búsqueda
python -m scripts.resolve_dnma_substances --dump <dump>   # puente con el DNMA
```

⚠️ La base se abre con `immutable=1`: **un cambio del ETL no se ve hasta
reiniciar el servicio**.

### El extra `ml`

El clasificador de severidad (DeBERTa zero-shot) es opcional. PyTorch no publica
wheels de macOS x86_64, así que con él en el set base la suite no instala en un
Mac Intel. Sin el modelo, el clasificador cae a un fallback por regex.

```bash
uv sync --extra ml        # el Dockerfile lo instala siempre
```

---

## API

| | |
|---|---|
| `POST /interactions` | `{"drugs": ["warfarin", "ibuprofen"]}` → pares con gravedad, evidencia y procedencia |
| `GET /drugs/search?q=` | autocompletado por alias |
| `GET /health`, `/health/data` | sin autenticación |

Autenticación por header `X-API-Key`. **Sin `API_KEY` seteada el servicio
responde 503**, no queda abierto. Para desarrollo, `CONSILIO_ALLOW_NO_API_KEY=1`.

### Procedencia y precedencia

Cada hecho lleva su origen, y ante dos filas para el mismo par gana la de mayor
autoridad:

```
recetalia  >  ddinter  >  openfda
```

Lo que revisó un farmacéutico pisa a todo lo importado. Los hallazgos de openFDA
salen con `uncertain: true`: son inferencia sobre texto libre, y quien los lea
tiene que poder distinguirlos de una severidad estructurada.

Ese mismo criterio permite refrescar DDInter sin perder curación propia: un
re-seed borra `source='ddinter'` y nada más.

---

## Licencias

**El código de este repositorio es MIT.**

Los datos son otra cosa, y cada fuente tiene su régimen:

| Fuente | Licencia | Uso comercial |
|---|---|---|
| **openFDA** | CC0 1.0 | sí, sin restricción |
| **RxNorm / RxClass / MED-RT** (NLM) | sin licencia requerida | sí |
| **DDInter 2.0** | **CC BY-NC-SA 4.0** | **no** |

⚠️ **DDInter es NonCommercial.** Aporta el 98 % de los pares, y su cláusula
gobierna la **distribución y explotación comercial**, no tener una copia local
para desarrollar o evaluar. Por eso la base **no se hornea en la imagen**: se
monta. Antes de cualquier uso comercial hay que resolverlo — negociando licencia
con el equipo de DDInter, o reconstruyendo la base sólo con las fuentes
permisivas, que el esquema soporta sin cambios de código.

La licencia de DDInter que declara este código proviene del repositorio de
origen; conviene verificarla en <https://ddinter2.scbdd.com/>.

---

## Origen

Consilio es un fork de
[SPerekrestova/pillchecker-api](https://github.com/SPerekrestova/pillchecker-api)
(MIT), de Svetlana Perekrestova. De ahí vienen el pipeline de construcción de la
base DDInter, el crosswalk con RxNorm y buena parte de la infraestructura de
pruebas.

Qué cambió en el fork:

- Se quitó todo lo que no es interacciones: OCR, NER, parser de dosis y el
  endpoint `/analyze`.
- Esquema propio con procedencia por fila, que habilita curación que sobrevive a
  los re-seeds.
- Pares derivados de openFDA y expansión por clase, que el original no tenía.
- Alertas fármaco-patología desde MED-RT.
- Puente con el DNMA del MSP uruguayo.
- Interfaz de consulta propia.
- La API key dejó de fallar abierta; el rate limit dejó de ser 10/min fijo.

---

## Advertencia

Consilio genera información automáticamente a partir de fuentes públicas.
**No sustituye el criterio clínico.** Que no se encuentre una interacción
documentada no significa que no exista.
