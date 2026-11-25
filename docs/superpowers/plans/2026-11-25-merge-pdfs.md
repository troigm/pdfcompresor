# Combinar y comprimir PDFs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nuevo modo `merge` en MochaCompress: N PDF (factura + albaranes) en el orden elegido → un PDF combinado y comprimido con Ghostscript en una sola pasada.

**Architecture:** Modelo hijo `JobInput` con `position`; tarea Celery `merge_pdfs` que reutiliza la construcción de argumentos de Ghostscript de `compress_pdf` (extraída a `build_gs_command`); la vista `upload` acepta `pdf_files` múltiples; la UI mantiene una lista ordenable (drag nativo HTML5) que sincroniza el `<input multiple>` vía `DataTransfer`.

**Tech Stack:** Django 6.0, Celery 5.6, PostgreSQL 18, Ghostscript, poppler-utils (`pdfinfo`/`pdftotext` en tests), Bootstrap 5.3 + HTMX 2.0.4.

**Spec:** `docs/superpowers/specs/2026-11-25-combine-pdfs-design.md`

## Global Constraints

- Sin dependencias Python ni apt nuevas.
- Límites merge: mínimo **2** ficheros, máximo **100**; cada uno `.pdf` y ≤ **100 MB**; total ≤ **300 MB**.
- Timeout de Ghostscript en merge: **600 s**; `max_retries=2`, `default_retry_delay=10` (igual que hoy).
- Nombre del resultado = `original_filename` del primer fichero de la lista.
- Sin fallback a original: si el combinado pesa más que la suma de entradas, se entrega igual.
- Textos de UI en español; código, identificadores y commits en inglés.
- Los tests corren en Docker (no hay `gs` en el Mac): `docker compose run --rm web python manage.py test compressor -v 2`. Cada test que escribe ficheros usa `@override_settings(MEDIA_ROOT=<tempdir>)`.
- Commits terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Mismo fichero añadido dos veces** → aparece dos veces en el PDF final (la lista manda). Test en Task 4.
2. **Una entrada corrupta entre muchas** → job `failed` con `error_message` no vacío, sin excepción fuera de la tarea. Test en Task 3.
3. **Nombres con acentos, espacios y paréntesis** (`Albarán nº 12 (copia).pdf`) → se combinan y el resultado conserva el nombre del primero. Test en Task 3.
4. **Cambiar de modo con ficheros ya elegidos** → la selección se limpia, no se envía un merge como compress ni al revés. Verificación manual en Task 5.
5. **Combinado más grande que la suma** → la tarjeta no muestra un `-−5%` absurdo: el badge de ahorro solo aparece si `savings_percent > 0`. Verificación en Task 5.

---

### Task 1: Extraer `build_gs_command` y montar los tests

**Files:**
- Modify: `compressor/tasks.py` (bloque `cmd = [...]` de `compress_pdf`)
- Create: `compressor/tests/__init__.py`, `compressor/tests/test_gs_command.py`

**Interfaces:**
- Produces: `build_gs_command(input_paths: list[str], output_path: str, preset: str, compatibility: str, pdfa_def_path: str | None, gs_bin: str = "gs") -> list[str]` en `compressor/tasks.py`. Devuelve exactamente los mismos flags que hoy para cada rama; las rutas de entrada van al final en el orden recibido (en PDF/A, `pdfa_def_path` justo antes de las entradas).

- [ ] **Step 1: Write the failing tests** (`compressor/tests/test_gs_command.py`, `SimpleTestCase`)

```python
def test_standard_command_keeps_flags_and_input_order(self):
    cmd = build_gs_command(["/a.pdf", "/b.pdf"], "/out.pdf", "ebook", "pdf-1.7", None)
    assert cmd[0] == "gs"
    assert "-dCompatibilityLevel=1.7" in cmd and "-dPDFSETTINGS=/ebook" in cmd
    assert "-dSAFER" in cmd and "-sOutputFile=/out.pdf" in cmd
    assert cmd[-2:] == ["/a.pdf", "/b.pdf"]

def test_pdfa_command_puts_def_before_inputs(self):
    cmd = build_gs_command(["/a.pdf", "/b.pdf"], "/out.pdf", "printer", "pdfa-2b", "/def.ps")
    assert "-dPDFA=2" in cmd and "-dPDFSETTINGS=/printer" in cmd
    assert cmd[-3:] == ["/def.ps", "/a.pdf", "/b.pdf"]

def test_unknown_compatibility_falls_back_to_1_4(self):
    cmd = build_gs_command(["/a.pdf"], "/out.pdf", "ebook", "bogus", None)
    assert "-dCompatibilityLevel=1.4" in cmd
```

- [ ] **Step 2: Run** `docker compose run --rm web python manage.py test compressor -v 2` → FAIL (`ImportError: build_gs_command`).
- [ ] **Step 3: Implement `build_gs_command`** moviendo literalmente las dos listas actuales; `compress_pdf` pasa `[input_path]` y `getattr(settings, "GHOSTSCRIPT_BIN", "gs")`.
- [ ] **Step 4: Run** the same command → 3 tests PASS.
- [ ] **Step 5: Commit** `refactor: extract build_gs_command from compress_pdf`

---

### Task 2: Modelo `JobInput`, modo `merge` y borrado unificado

**Files:**
- Modify: `compressor/models.py`, `compressor/views.py` (`download`), `compressor/management/commands/cleanup_jobs.py`
- Create: `compressor/migrations/0005_merge_mode_jobinput.py` (vía `makemigrations`), `compressor/tests/test_models.py`

**Interfaces:**
- Produces:
  - `JobMode.MERGE = "merge", "Combinar y comprimir"`.
  - `PDFJob.original_file` → `blank=True`.
  - `class JobInput(models.Model)`: `job = ForeignKey(PDFJob, on_delete=CASCADE, related_name="inputs")`, `file = FileField(upload_to="uploads/%Y/%m/%d/")`, `original_filename = CharField(max_length=255)`, `size = BigIntegerField()`, `position = PositiveIntegerField()`; `Meta.ordering = ["position"]`.
  - `PDFJob.delete_with_files() -> None`: borra del storage `original_file`, `compressed_file` y el `file` de cada `inputs` (ignorando los que falten) y luego `self.delete()`.

- [ ] **Step 1: Write the failing tests** (`test_models.py`, `TestCase`, `MEDIA_ROOT` temporal)

```python
def test_inputs_ordered_by_position(self):
    # crea job merge + JobInput con position 2, 0, 1
    assert [i.position for i in job.inputs.all()] == [0, 1, 2]

def test_delete_with_files_removes_every_file(self):
    # job con original_file, compressed_file y 2 inputs, ficheros reales en MEDIA_ROOT
    job.delete_with_files()
    assert not PDFJob.objects.filter(id=job_id).exists()
    assert JobInput.objects.count() == 0
    assert all(not os.path.exists(p) for p in paths)

def test_delete_with_files_tolerates_missing_files(self):
    # borra a mano un input del disco antes; no debe lanzar
    job.delete_with_files()
```

- [ ] **Step 2: Run** tests → FAIL (`ImportError: JobInput`).
- [ ] **Step 3: Implement** model changes; `docker compose run --rm web python manage.py makemigrations compressor -n merge_mode_jobinput`.
- [ ] **Step 4: Replace** the manual file removal in `download` (bucle `for path in (...)` + `job.delete()`) and in `cleanup_jobs` with `job.delete_with_files()`. `download` debe leer `content` antes de borrar, como hoy.
- [ ] **Step 5: Run** all tests → PASS.
- [ ] **Step 6: Commit** `feat: JobInput model and merge mode with unified file cleanup`

---

### Task 3: Tarea `merge_pdfs`

**Files:**
- Modify: `compressor/tasks.py`
- Create: `compressor/tests/test_merge_task.py`

**Interfaces:**
- Consumes: `build_gs_command` (Task 1), `JobInput` / `JobMode.MERGE` (Task 2).
- Produces: `@shared_task(bind=True, max_retries=2, default_retry_delay=10) merge_pdfs(self, job_id: str) -> None`. Estados igual que `compress_pdf`. Al completar: `compressed_file` guardado con nombre `job.original_filename`, `original_size` = suma de `inputs.size`, `compressed_size`, `compression_ratio`, `completed_at`. Timeout `subprocess.run(..., timeout=600)`. Gestiona `pdfa_def_path` y temporales igual que `compress_pdf`.

- [ ] **Step 1: Write the failing tests** (`TestCase`, `MEDIA_ROOT` temporal; ejecutar con `merge_pdfs.apply(args=[str(job.id)])`). Helper `make_pdf(label: str, pages: int) -> bytes` que genera un PDF con `gs -sDEVICE=pdfwrite -o <tmp> -c "<PostScript que escribe label en cada página> showpage"`.

```python
def test_merges_in_position_order(self):
    # inputs: "DOC-A" 1 pág (position 0), "DOC-B" 2 págs (position 1), "DOC-C" 1 pág (position 2)
    job.refresh_from_db()
    assert job.status == JobStatus.COMPLETED
    assert pdfinfo_pages(job.compressed_file.path) == 4
    assert "DOC-A" in pdftotext_page(path, 1)
    assert "DOC-B" in pdftotext_page(path, 2)
    assert "DOC-C" in pdftotext_page(path, 4)

def test_result_named_after_first_input_with_accents(self):
    # primer input original_filename = "Factura nº 12 (copia).pdf"
    assert job.compressed_file.name.endswith(".pdf")
    assert job.original_filename == "Factura nº 12 (copia).pdf"
    assert job.original_size == sum(i.size for i in job.inputs.all())

def test_corrupt_input_marks_job_failed(self):
    # input 2 de 3 son bytes b"not a pdf"
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert job.error_message
```

`pdfinfo_pages` / `pdftotext_page` son helpers del test con `subprocess` (`pdfinfo` → línea `Pages:`; `pdftotext -f N -l N path -`).

- [ ] **Step 2: Run** tests → FAIL (`ImportError: merge_pdfs`).
- [ ] **Step 3: Implement `merge_pdfs`** con `build_gs_command([i.file.path for i in job.inputs.all()], ...)`.
- [ ] **Step 4: Run** all tests → PASS. Si `test_corrupt_input_marks_job_failed` pasa sin fallar gs (gs a veces repara), cambiar el input corrupto por un PDF cifrado con contraseña de usuario (`gs ... -sUserPassword=x`) y anotarlo en el commit.
- [ ] **Step 5: Commit** `feat: merge_pdfs Celery task`

---

### Task 4: Vista `upload` en modo merge y ajustes de subida

**Files:**
- Modify: `compressor/views.py`, `pdf_compressor/settings.py:85-86`
- Create: `compressor/tests/test_upload_merge.py`

**Interfaces:**
- Consumes: `JobInput`, `JobMode.MERGE`, `merge_pdfs`.
- Produces: en `views.py` las constantes `MERGE_MIN_FILES = 2`, `MERGE_MAX_FILES = 100`, `MERGE_MAX_TOTAL_SIZE = 300 * 1024 * 1024`. Con `mode=merge` la vista lee `request.FILES.getlist("pdf_files")`, valida, crea `PDFJob` (`original_filename` y `preset`/`compatibility` como hoy, `original_size` = suma) + un `JobInput` por fichero con `position` = índice en la lista, en una `transaction.atomic()`, y encola `merge_pdfs.delay` en `transaction.on_commit`. Ninguna validación fallida crea job ni guarda ficheros. Respuesta 400 con el mismo HTML de alerta.
- Settings: `FILE_UPLOAD_MAX_MEMORY_SIZE` vuelve al default de Django (2,5 MB, borrar la línea) para que las subidas vayan a disco y no a RAM (con 300 MB por petición × 3 workers). `DATA_UPLOAD_MAX_NUMBER_FILES = 101` con comentario: uno más que `MERGE_MAX_FILES` para que la vista dé el mensaje legible en vez de un 400 genérico de Django.

Mensajes exactos:
- `< 2`: «Selecciona al menos 2 archivos PDF para combinar.»
- `> 100`: «Máximo 100 archivos por combinación.»
- no PDF: «Solo se permiten archivos PDF: {nombre}.»
- `> 100 MB` uno: «{nombre} excede el límite de 100 MB.»
- total: «El total excede el límite de 300 MB.»

- [ ] **Step 1: Write the failing tests** (`TestCase`, `MEDIA_ROOT` temporal, `@patch("compressor.views.merge_pdfs.delay")`, `captureOnCommitCallbacks(execute=True)`)

```python
def test_creates_job_with_inputs_in_upload_order(self):
    # post mode=merge, pdf_files=[fra.pdf, alb1.pdf, alb2.pdf]
    assert resp.status_code == 200
    job = PDFJob.objects.get()
    assert job.mode == JobMode.MERGE and job.original_filename == "fra.pdf"
    assert [i.original_filename for i in job.inputs.all()] == ["fra.pdf", "alb1.pdf", "alb2.pdf"]
    mock_delay.assert_called_once_with(str(job.id))

def test_same_file_twice_is_kept_twice(self):
    # pdf_files=[a.pdf, a.pdf]
    assert job.inputs.count() == 2

def test_rejects_single_file(self):           # 400, "al menos 2", 0 jobs
def test_accepts_100_files(self):             # 200, 100 inputs
def test_rejects_101_files(self):             # 400, "Máximo 100", 0 jobs
def test_rejects_non_pdf(self):               # [a.pdf, b.txt] → 400, "b.txt", 0 jobs
def test_rejects_total_over_300mb(self):      # @patch("compressor.views.MERGE_MAX_TOTAL_SIZE", 10) → 400, 0 jobs
def test_compress_mode_unchanged(self):       # pdf_file + mode=compress → job compress sin inputs
```

- [ ] **Step 2: Run** tests → FAIL.
- [ ] **Step 3: Implement** la rama merge en `upload` (función privada `_upload_merge(request) -> HttpResponse` para no inflar `upload`) y los cambios de settings.
- [ ] **Step 4: Run** all tests → PASS.
- [ ] **Step 5: Commit** `feat: accept multi-file uploads for merge mode`

---

### Task 5: Interfaz, tarjeta del job y documentación

**Files:**
- Modify: `compressor/templates/compressor/index.html`, `compressor/templates/compressor/_job_card.html`, `README.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: campo POST `pdf_files` (múltiple, orden = orden de envío), `mode=merge`.

- [ ] **Step 1: Selector de modo** → tres columnas (`col-4`): tercera tarjeta `mode-merge`, icono `bi-files`, «Combinar y comprimir», subtítulo «Factura + albaranes en un PDF». Presets y compatibilidad visibles en `compress` y `merge`; nota de extracción solo en `extract_images`. Botón: «Combinar y comprimir» / «Combinando...». Generalizar `applyMode()` a tres modos con clases `.mode-compress`, `.mode-extract`, `.mode-merge` (o `data-modes="compress merge"`); cambiar de modo llama a `resetForm()`.
- [ ] **Step 2: Lista ordenable (solo merge)** → segundo input oculto `<input type="file" name="pdf_files" id="merge-input" multiple accept=".pdf,application/pdf" class="d-none">`; en merge, la drop zone y el clic **añaden** ficheros a un array JS `mergeFiles` (descartar los no-PDF con aviso en línea; no pasar de 100 con aviso). Lista con `max-height: 50vh; overflow-y: auto`, cada fila `draggable="true"` con ≡, nº de orden, nombre, tamaño y ✕; contador «N ficheros · X MB». Tras cada cambio (añadir, quitar, soltar) reconstruir `merge-input.files` con `new DataTransfer()` en el orden de `mergeFiles`. Botón activo solo con ≥ 2 ficheros y total ≤ 300 MB. En merge, `pdf_file` queda vacío; en compress/extract, `merge-input` vacío.
- [ ] **Step 3: Tarjeta del job** → en merge, subtítulo «{{ job.inputs.count }} ficheros · Combinar y comprimir · {preset}»; badge de ahorro solo `{% if job.savings_percent > 0 %}` (aplica a todos los modos).
- [ ] **Step 4: Verificación manual** con `docker compose up --build -d` en `http://localhost:8000` (Playwright MCP o a mano):
  - 3 PDF → reordenar arrastrando → combinar → descargar → el orden de páginas coincide con la lista.
  - Quitar uno con ✕ antes de enviar → no aparece en el resultado.
  - Elegir ficheros en merge y cambiar a «Comprimir» → la lista se vacía y el botón queda desactivado.
  - Modos «Comprimir» y «Extraer imágenes» siguen funcionando.
  - Subida de ~90 ficheros pequeños: la lista hace scroll y el job completa.
- [ ] **Step 5: Docs** → README: fila «Combinar y comprimir» en la tabla de modos + subsección con límites (2–100 ficheros, 100 MB c/u, 300 MB total, timeout 600 s, sin fallback a original). CHANGELOG `## [1.4.0] - 2026-11-25` con Añadido / Cambiado (`FILE_UPLOAD_MAX_MEMORY_SIZE` al default, `DATA_UPLOAD_MAX_NUMBER_FILES = 101`, `build_gs_command`, `delete_with_files`).
- [ ] **Step 6: Run** suite completa → PASS.
- [ ] **Step 7: Commit** `feat: merge-and-compress UI with reorderable file list`

---

## Fuera de este plan (requiere OK aparte)

Despliegue en la .245: antes, `git status`/`git diff` en `/srv/projects/mochacompress` contra `main` (posibles cambios del bastionado del 2026-11-18 sin commitear), revisar que Traefik no limita el tamaño del cuerpo (`dynamic/middlewares.yml`, sin middleware `buffering`), que Gunicorn `--timeout 120` aguanta 300 MB desde la VPN (si no, subirlo), y presentar el bloque Alcance/Riesgo/Caída/Backup/Rollback. Después, documentarlo en el as-built de la .245.
