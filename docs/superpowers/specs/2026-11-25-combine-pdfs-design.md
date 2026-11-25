# Combinar y comprimir PDFs — diseño

Fecha: 2026-11-25 · Cliente: Comrec · App: MochaCompress (`pdf.comrec.lan`, VM .245)

## Intención

Administración de Comrec envía a un cliente la factura junto con sus albaranes en un único PDF, que
deja a mano en una carpeta de SharePoint compartida con ese cliente. Hoy no hay herramienta interna
para juntarlos. Nuevo modo **"Combinar y comprimir"**: varios PDF de entrada → un PDF combinado y
comprimido en un solo paso.

## Objetivos

- Subir N PDF (factura + albaranes), en orden de inserción, con posibilidad de reordenar y quitar.
- Combinar y comprimir a la vez, con los mismos presets de calidad y compatibilidad que el modo
  "Comprimir".
- Misma experiencia que los modos actuales: tarjeta HTMX con progreso, descarga única con borrado.

## No objetivos

- Subida automática a SharePoint (la hacen ellos a mano). Posible fase 2 con Graph si se usa.
- Edición de páginas (rotar, quitar páginas sueltas, dividir).
- Soporte táctil / móvil para reordenar.

## Anti-objetivos

- Que el orden del PDF final no coincida con el que se ve en pantalla.
- Dejar ficheros de entrada huérfanos en `media/` tras descargar, fallar o caducar.

## Enfoques considerados

| Decisión | Elegido | Descartado | Por qué |
|---|---|---|---|
| Motor | **Ghostscript solo**: una llamada `pdfwrite` con todas las entradas en orden | `pypdf` combina + Ghostscript comprime | Cero dependencias nuevas, una pasada, reutiliza los flags de `compress_pdf`. El fallback "entregar sin comprimir si crece" de la alternativa no compensa para escaneos |
| Almacenar entradas | **Modelo hijo `JobInput`** (`job` FK, `file`, `original_filename`, `size`, `position`) | JSONField de rutas en `PDFJob` | Orden explícito, integridad, borrado uniforme |
| Reordenar | **Drag & drop nativo HTML5** + botón quitar, sin librerías | SortableJS | Uso en escritorio; ~30 líneas de JS |

Decidido con Tommy el 2026-11-25.

## Diseño

**Modelo**
- `JobMode.MERGE = "merge", "Combinar y comprimir"`.
- `JobInput(job=FK(PDFJob, on_delete=CASCADE, related_name="inputs"), file, original_filename, size, position)`, `ordering=["position"]`.
- En modo merge, `PDFJob.original_file` queda vacío (`blank=True` → migración);
  `original_filename` = nombre del primer fichero; `original_size` = suma de entradas.

**Vista `upload`**
- Modo `merge`: `request.FILES.getlist("pdf_files")`, el orden de la lista es el orden final (el JS
  reconstruye el `FormData` según la lista visible).
- Validación: mínimo 2 ficheros, máximo **100** (hay facturas con hasta 90 albaranes); cada uno
  `.pdf` y ≤ 100 MB; total ≤ 300 MB. Mensajes en el mismo formato de alerta que hoy.
- `DATA_UPLOAD_MAX_NUMBER_FILES` (Django, default 100) se fija explícitamente en settings para que
  el límite no dependa del default; nuestra validación da el mensaje legible.
- Comprobar que `DATA_UPLOAD_MAX_MEMORY_SIZE`/`FILE_UPLOAD_*`, Gunicorn (`--timeout 120`) y Traefik
  aguantan 300 MB; ajustar si no.
- La lista de la UI debe seguir siendo usable con 90+ ficheros: altura máxima con scroll y contador
  "N ficheros · X MB".

**Tarea Celery `merge_pdfs`**
- Misma construcción de `cmd` que `compress_pdf` (incluido PDF/A) pero con todas las rutas de
  `job.inputs` en orden al final. Refactor mínimo: extraer la construcción de args a una función
  compartida en lugar de duplicarla.
- Sin fallback a "original": si el resultado pesa más que la suma, se entrega igual.
- Resultado en `compressed_file` con nombre `original_filename` (el del primer fichero).
- Timeout de gs **600 s** (con 100 entradas escaneadas 300 s puede quedarse corto), 2 reintentos.

**Descarga y limpieza**
- `download` y `cleanup_jobs` borran también los ficheros de `job.inputs` antes de `job.delete()`.

**Interfaz**
- Tercera tarjeta de modo. En merge, el input pasa a `multiple` y aparece la lista ordenable
  (≡ arrastrar, ✕ quitar, tamaño). Presets y compatibilidad visibles, como en "Comprimir".
- La tarjeta del job muestra nº de ficheros, tamaño total de entrada → salida.

**Tests** (no hay ninguno hoy): orden de entradas respetado en el comando gs, validaciones de la
vista (1 fichero, 101 ficheros, no-PDF, exceso de tamaño), borrado de entradas en `download` y
`cleanup_jobs`, y un test de integración con gs real combinando dos PDF y comprobando nº de páginas.

## Despliegue

Antes de desplegar en `/srv/projects/mochacompress`: comparar con el repo local (el bastionado del
2026-11-18 tocó etiquetas Traefik, posible divergencia no commiteada). Migración nueva →
`migrate` en el arranque. Documentar en la nota as-built de la .245.

## Queda para el builder

Estilo de la lista ordenable (Catppuccin Mocha existente), textos exactos de la UI, forma concreta
del refactor de args de gs.
