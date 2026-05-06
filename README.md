# MochaCompress

Aplicación web para comprimir archivos PDF y extraer imágenes embebidas. Usa Ghostscript para compresión y `pdfimages` (poppler-utils) para extracción. Interfaz oscura Catppuccin Mocha con procesamiento asíncrono.

## Stack

- **Backend**: Django 6.0 + Celery 5.6 + Redis 7
- **Base de datos**: PostgreSQL 18
- **Motor PDF**: Ghostscript (compresión) + poppler-utils (extracción de imágenes)
- **Frontend**: Bootstrap 5.3 + HTMX 2.x
- **Despliegue**: Docker Compose

## Inicio rápido

```bash
cp .env.example .env
docker compose up --build -d
```

La app estará en [http://localhost:8000](http://localhost:8000).

## Funcionalidades

### Modos de operación
La interfaz ofrece dos modos seleccionables antes de la subida:

| Modo | Resultado | Motor |
|------|-----------|-------|
| Comprimir PDF | PDF comprimido | Ghostscript |
| Extraer imágenes | ZIP con las imágenes embebidas en su resolución original | `pdfimages` (poppler-utils) |

### Compresión de PDFs
- Subida por arrastre (drag & drop) o selección de archivo
- Límite de 100 MB por archivo
- Procesamiento en background con Celery
- Progreso en tiempo real via HTMX (polling cada 2s)
- Si el archivo comprimido es mayor que el original, se sirve el original
- **Descarga única**: al descargar el resultado se elimina el job y los archivos físicos del servidor; la página se recarga automáticamente para ocultar el job borrado

### Extracción de imágenes
- Ejecuta `pdfimages -all` para extraer cada imagen embebida en su formato original (JPEG, PNG, JBIG2, etc.)
- Empaqueta el resultado en un ZIP con compresión deflate
- Falla con mensaje claro si el PDF no contiene imágenes embebidas extraíbles
- Misma descarga única + borrado automático que el flujo de compresión

### Presets de calidad
La resolución (ppp / dpi) se muestra en cada botón de la interfaz.

| Preset | PPP | Uso |
|--------|-----|-----|
| Pantalla | 72 | Mínimo tamaño, para pantalla/web |
| eBook | 150 | Equilibrado (default) |
| Impresora | 300 | Alta calidad para impresión |
| Preimpresión | 300 | Máxima calidad profesional |

### Compatibilidad PDF
| Nivel | Descripción |
|-------|-------------|
| PDF 1.4 | Máxima compatibilidad, funciona en cualquier visor |
| PDF 1.5 | Mejor compresión con object streams |
| PDF 1.7 | Estándar ISO moderno (default) |
| PDF/A-2b | Archivado a largo plazo, cumple normativa legal |

> PDF/A elimina enlaces, marcadores y formularios. El tamaño puede aumentar.

### Motor Ghostscript
- Fuentes incrustadas y subconjuntos optimizados en todos los modos
- Submuestreo bicúbico para imágenes color y escala de grises
- Perfil ICC sRGB auto-detectado para generación PDF/A
- Timeout de 5 minutos por archivo, 2 reintentos automáticos

## Servicios Docker

| Servicio | Imagen | Función |
|----------|--------|---------|
| web | python:3.14-slim + Gunicorn | Servidor web |
| celery | mismo build | Worker de compresión (2 concurrentes) |
| celery-beat | mismo build | Scheduler para tareas periódicas |
| db | postgres:18-alpine | Base de datos |
| redis | redis:7-alpine | Broker de mensajes |

Los servicios `web` y `celery` comparten un volumen `media_data` para que el worker acceda a los uploads y web sirva los comprimidos.

## Limpieza de archivos

```bash
docker compose exec web python manage.py cleanup_jobs
```

Elimina jobs y archivos con más de 24 horas (configurable via `COMPRESSED_FILE_TTL_HOURS`).

## Variables de entorno

Ver `.env.example` para la lista completa.

| Variable | Default | Descripción |
|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | — | Clave secreta de Django |
| `DJANGO_DEBUG` | `0` | Modo debug |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | URL del broker Redis |
| `GHOSTSCRIPT_BIN` | `gs` | Ruta al binario de Ghostscript |
| `COMPRESSED_FILE_TTL_HOURS` | `24` | Horas antes de eliminar archivos |
