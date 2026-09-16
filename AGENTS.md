# Reglas del repositorio

Consilio es un servicio de seguridad en la prescripción. Un error acá no rompe
una pantalla: puede hacer que un médico recete algo que no debía, o peor, que
confíe en un silencio. Estas reglas salen de eso.

## Lo que nunca se hace

1. **No inventar datos que parezcan evidencia.** Si una fuente aporta el par y
   la gravedad pero no el mecanismo, la respuesta lo dice. Rellenar con una
   plantilla que repite los nombres ocupa el lugar de la evidencia sin serlo.
   (Pasó: `"Interaction reported in DDInter 2.0 for X + Y"`.)

2. **No confundir "sin evidencia" con "seguro".** Un par que no está en la base
   sale como *no encontrado*, nunca como *sin riesgo*. Un sistema que calla
   cuando no sabe enseña a confiar en su silencio.

3. **No mapear por aproximación sin verificar.** El score de `approximateTerm`
   de RxNorm no discrimina: medido, una cadena inventada puntúa 9,4 contra 10,5
   de un match perfecto. La aceptación la decide comparar el nombre devuelto con
   el consultado. Mapear en silencio una sustancia desconocida al fármaco
   equivocado es peor que no mapearla.

4. **No degradar en silencio hacia el usuario.** Si el motor no responde, la
   respuesta lo dice explícitamente. Y un error al pintar no puede disfrazarse
   de error de red: eso ya produjo una pantalla con resultados correctos y un
   cartel de error al mismo tiempo.

## Procedencia

Cada hecho lleva `source`. Es lo que permite refrescar una fuente sin perder la
curación propia: un re-seed borra `source='ddinter'` y nada más. Editar filas
importadas en el lugar funciona hasta el primer re-seed, que se lleva meses de
revisión farmacéutica sin avisar.

Precedencia: `recetalia > ddinter > openfda`. Vive en SQL (`_PRECEDENCE`), no en
convención.

## ETL y runtime

El ETL escribe, el runtime lee. La base se abre `mode=ro&immutable=1`.

**Ninguna request de un médico puede disparar una descarga, un rebuild ni una
llamada a un tercero por datos de referencia.** Si hace falta un dato nuevo, se
precalcula.

Corolario: un cambio del ETL no se ve hasta reiniciar el servicio.

## Mediciones

Los números de los comentarios y los commits salen de correr algo, no de
estimar. Si un comentario dice "descartó 1.511", ese número se midió. Cuando una
medición contradice algo escrito, se corrige el texto en el lugar — no se agrega
una nota al pie.

## Licencias

Antes de sumar una fuente de datos, verificar su licencia **en la fuente** y
anotarla en el README. `NonCommercial`, `ShareAlike` y `NoDerivatives` cambian
qué se puede distribuir.

La base de conocimiento **no se hornea en la imagen**. Se monta.

## Tests

`uv run pytest -q` tiene que pasar antes de cualquier commit.

El gate de regresión (`tests/regression/`) compara contra severidades curadas.
Si falla, **no se ablanda**: o se arregla el motor, o se documenta el hueco con
su motivo medido en `KNOWN_GAPS` para que quede rojo explicado en vez de verde
falso.
