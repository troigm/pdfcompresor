# Changelog

## [1.0.0] - 2026-03-21

### Añadido
- Compresión de PDFs con Ghostscript (presets: pantalla, ebook, impresora, preimpresión)
- 4 niveles de compatibilidad PDF: 1.4, 1.5, 1.7 y PDF/A-2b
- Generación PDF/A-2b con perfil ICC sRGB auto-detectado y PDFA_def.ps dinámico
- Subida de archivos por drag & drop y selección manual (máx. 100 MB)
- Procesamiento asíncrono con Celery + Redis
- Actualización en tiempo real con HTMX (polling cada 2s)
- Interfaz Catppuccin Mocha con glassmorphism (Bootstrap 5.3 dark mode)
- Descarga del archivo comprimido con nombre original
- Si el comprimido es mayor que el original, se sirve el original
- Management command `cleanup_jobs` para eliminar archivos antiguos
- Despliegue con Docker Compose (5 servicios: web, celery, celery-beat, PostgreSQL, Redis)
- Volumen compartido `media_data` entre web y celery worker
- Aviso visual al seleccionar PDF/A sobre eliminación de enlaces y marcadores
- Fuentes incrustadas y subconjuntos optimizados en todos los modos
- Reintentos automáticos (2 intentos, delay 10s) en caso de fallo
- Timeout de 5 minutos por compresión

### Defaults
- Preset: eBook (150 dpi, equilibrado)
- Compatibilidad: PDF 1.7 (Moderno)
