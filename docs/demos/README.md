# Videos demo de Consilio

Seis videos MP4 (1440×900, 30 fps) grabados sobre PRE (`consiliopre.medicinainteligente.ai`) con la skill `demo-video`:
Playwright + screencast de CDP + ffmpeg. Leyendas, cartelas, cursor y resaltado se inyectan en la página.

| # | archivo | qué muestra |
|---|---|---|
| 1 | `1-interacciones` | autocompletado, cruce de 4 medicamentos, gravedad, qué hacer y fuente |
| 2 | `2-duplicidad-terapeutica` | duplicidad de clase ATC y una duplicidad suprimida con su motivo |
| 3 | `3-perfil-del-paciente` | «Ejemplo con paciente»: alergia, CIE-10, contraindicación renal, criterios en el anciano |
| 4 | `4-embarazo-y-funcion-hepatica` | perfil cargado a mano: embarazo + hepatopatía |
| 5 | `5-resultados-y-transparencia` | filtros, copiar/imprimir, «¿Qué evalúa?», panel Transparencia, inglés |
| 6 | `6-extra-api-para-integradores` | lo mismo por `curl` (salidas reales de PRE en `api/oN.txt`) |

Regrabar (la API key de PRE nunca va al repo ni a la pantalla):

    cd docs/demos && npm i
    DEMO_TOKEN=$(cat ~/.config/consilio-demo/key) node grabar.mjs todos   # o: 3 5
    # salen en ~/Desktop/demo-consilio

Si cambian los datos de la base, regenerar `api/oN.txt` con los mismos comandos que se ven en el video 6
y revisar las leyendas: cada una se verificó contra PRE el 2026-10-09.
