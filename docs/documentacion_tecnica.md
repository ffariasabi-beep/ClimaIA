# Integración de inteligencia artificial con Groq

ClimaIA utiliza Groq para las funciones generales de inteligencia artificial.
El Centro de investigaciones usa Workers AI de Cloudflare de forma
independiente; ningún otro módulo cambia de proveedor. La integración Flask
se concentra en los servicios de cada módulo y conserva sus prompts, datos de
entrada y responsabilidades.

La aplicación envía el contexto ya calculado por ClimaIA —por ejemplo,
observaciones meteorológicas, anomalías y comparaciones entre localidades— a
`POST https://api.groq.com/openai/v1/chat/completions`. Groq interpreta ese
contexto; no reemplaza los servicios meteorológicos ni altera los análisis
previos. La interpretación del observatorio mantiene la distinción entre
observaciones puntuales y tendencias climáticas.

El límite HTTP 429 mencionado por el observatorio puede provenir de
Open-Meteo, que es independiente de Groq. Si falla la consulta histórica, la
interpretación de Groq todavía puede describir las condiciones meteorológicas
actuales que estén disponibles, pero debe indicar que no hay evidencia para
inferir tendencias históricas. Para usar la IA se requiere `GROQ_API_KEY` y
un identificador válido en `GROQ_MODEL`.

## Centro de investigaciones

El asistente de `POST /research-center/api/messages` usa exclusivamente la API
OpenAI-compatible de Cloudflare Workers AI para sus respuestas y llamadas a
herramientas. No usa Groq como alternativa. El modelo predeterminado es
`@cf/meta/llama-3.3-70b-instruct-fp8-fast`, que admite function calling. La
configuración requiere `CLOUDFLARE_API_TOKEN` con permisos de Workers AI y
`CLOUDFLARE_ACCOUNT_ID`; `CLOUDFLARE_AI_MODEL` puede cambiar el modelo.

Estas variables deben permanecer en el `.env` local y no deben agregarse al
repositorio:

```dotenv
CLOUDFLARE_API_TOKEN=tu_token_de_cloudflare
CLOUDFLARE_ACCOUNT_ID=tu_account_id
CLOUDFLARE_AI_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast
```

## Asistente de investigación territorial

`POST /api/territory/research` conecta una consulta conversacional con la
selección del mapa y sus fechas. El servidor obtiene los mosaicos MODIS Aqua
reales de NASA GIBS y el perfil anual histórico de Open-Meteo que ya utiliza
el atlas, con la misma caché de 24 horas y control de límites. Si Open-Meteo
está limitado, ClimaIA reutiliza un perfil mensual 1991-2020 de su base local
cuando hay uno a menos de 5 km. Si tampoco existe, la consulta todavía puede
responder con la evidencia satelital y explica que no hay datos históricos
disponibles; no inventa tendencias. En una selección de área, la imagen
enviada a Groq corresponde al tile central; el perfil climático describe ese
punto, no toda el área.

Cuando hay una serie anual, Groq integra la evidencia visual de color real con
las anomalías, tendencias y referencia climática 1991-2020. Los perfiles
mensuales locales solo describen normales climáticas y no se presentan como
tendencias anuales. La conversación conserva hasta tres turnos anteriores en
el navegador para permitir repreguntas. La respuesta conversacional no se
presenta como detección cuantificada de cambios ni como prueba causal. Nubes,
resolución y diferencias de cobertura deben formar parte de la interpretación.

## Indicadores satelitales territoriales

`POST /api/territory/analytics` calcula indicadores para la selección del mapa
con los mismos períodos elegidos en el explorador. NASA GIBS proporciona NDVI
mensual de MODIS Terra; si el mes pedido no tiene cobertura utilizable, se
intentan hasta los tres meses anteriores y el resultado informa el período
efectivamente usado. ESA WorldCover proporciona las clases de cobertura 2020
(v100) y 2021 (v200), incluyendo cobertura de agua permanente y diferencias
cartográficas entre ambos mapas.

Los resúmenes se estiman sobre una imagen WMS remuestreada de 256 × 256
píxeles. Aunque WorldCover tiene producto nativo de 10 m, estos porcentajes no
son estadísticas calculadas sobre sus píxeles nativos. Los mapas 2020 y 2021
usan distintas versiones del algoritmo, por lo que las diferencias se
presentan como cambios de clasificación observados y no como transformaciones
reales confirmadas. La selección de un punto analiza un área de 5 × 5 km; las
áreas dibujadas están limitadas a 2.000 km por lado. Las respuestas parciales
incluyen advertencias del producto que no estuvo disponible.

El cliente puede superponer NDVI o cualquiera de los mapas WorldCover sobre
la base cartográfica. Los indicadores y su período no se guardan en la base de
ClimaIA; se consultan al ejecutar el análisis y se cachean temporalmente en el
servicio.

## Conexiones climáticas

Las similitudes comparan los perfiles mensuales 1991-2020 que ya están
almacenados en `ClimateProfile`, y muestran sus coordenadas en un mapa con
líneas desde la localidad de referencia. El mapa no implica que todo el
catálogo de localidades tenga un perfil: los candidatos disponibles dependen
de los perfiles generados y guardados previamente. La distancia climática
normalizada es un índice de ordenamiento, no un porcentaje.

En el mapa, el cliente compone visualmente el mosaico MODIS Aqua elegido con
hasta los dos días anteriores, dejando las zonas sin cobertura transparentes
para reducir franjas. Blue Marble de NASA completa visualmente los huecos; no
forma parte de la comparación. La composición es solo de presentación: el
servidor de investigación sigue usando la imagen del día elegido. La
comparación recorta cada ventana por separado (segunda fecha a la izquierda,
fecha principal a la derecha) y propone inicialmente la misma fecha del año
anterior.

Se usa `qwen/qwen3.8-27b` de forma predeterminada porque admite texto e imágenes
en la misma conversación. Groq actualmente lo clasifica como modelo de
previsualización; el identificador puede configurarse con `GROQ_MODEL`, pero
para conservar las consultas con mosaicos se debe elegir otro modelo con visión
que Groq tenga disponible.

Configuración en el archivo `.env` local:

```dotenv
GROQ_API_KEY=tu_clave_de_groq
GROQ_MODEL=qwen/qwen3.8-27b
```

La clave debe mantenerse fuera del repositorio. La API utiliza el encabezado
`Authorization: Bearer`, roles `system` y `user` dentro de `messages`, y
`max_completion_tokens`. Los mosaicos se envían como imágenes base64 en el
formato `image_url` de Chat Completions. La documentación oficial de visión y
modelos está disponible en
[Groq Vision](https://console.groq.com/docs/vision) y
[Groq Models](https://console.groq.com/docs/models). Los errores de
configuración, conexión, HTTP y respuestas vacías se informan explícitamente.
