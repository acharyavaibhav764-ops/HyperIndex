# v6 plan: PDF figure + VLM pipeline (phased)

**Replaces** the DeepSeek-OCR2 / vLLM v6 stub (now marked superseded) and the one-piece v5.10 patch.
**Scope:** PDF parsing only. DOCX/PPTX keep their v2 picture description untouched.
**Delivery:** one patch per phase (`v6_p0.patch` ... `v6_p6.patch`), applied in order, each with its own tests.
Every phase is opt-in until the A/B passes (`PDF_FIGURE_PIPELINE=v6`); the v5.9 code path stays byte-identical.

---

## 1. Facts this plan rests on

| Fact | Source |
|---|---|
| v5.9 figure cards never reached the output: `pic.bbox` does not exist (Docling keeps it in `prov`), image-route pages never called `process_pictures`, so SmolVLM captions ("home theater system", looped text, classifier labels as text) went to the index | Oct 17 chunk dump + `docling-core` introspection |
| Docling bboxes are bottom-left, PyMuPDF is top-left | `BoundingBox.to_top_left_origin` |
| `export_to_markdown()` prints the picture class unless `include_picture_classification=False` | ran it |
| Ollama runs in Docker with **no GPU reservation** and `OLLAMA_KEEP_ALIVE=-1`; the dev machine has a 4 GB GTX 1650 | `docker-compose.yml` |
| `chunker.contextualize()` prepends headings, so `text.startswith("Figure:")` is unreliable; tagging must search lines | chunker code |
| RapidOCR splits `SEM-IP ID1` into two detections and drops the space in `DBUS 2` -> `DBUS2` | ran real RapidOCR |
| Ingestion learns `doc_id` only after parsing | `api/v1/endpoints/documents.py` |

## 2. Phases

| Phase | Delivers | Switch | v6 tests (cumulative) | Whole suite |
|---|---|---|---|---|
| **P0** | `scripts/qwen_setup.py` (`start` / `status` / `verify` / `pull`): Qwen pulled into Ollama in a detached background process; `PDF_VLM_MODEL`; optional `docker-compose.gpu.yml` | none | 10 | 165 pass |
| **P1** | `import fitz` -> `import pymupdf` (code only; docstrings untouched), `pymupdf>=1.24.3` | none | 21 | 176 |
| **P2** | `parsers/pdf_v6/`: geometry, exact text-layer labels (with geometric `NAME ID<n>` pairing), skip gate, Figure cards; no SmolVLM on PDF pages | `PDF_FIGURE_PIPELINE=v6` | 46 | 201 |
| **P3** | Step-by-step illustration pages -> one ordered `Procedure (N illustrated steps)` chunk | `PDF_FIGURE_PROCEDURES` (on) | 60 | 215 |
| **P4** | RapidOCR labels (shaped like the text layer) + Ollama VLM connections validated by **exact** token match | `PDF_FIGURE_OCR`, `PDF_VLM_ENABLED` (off) | 78 (+1 slow) | 233 |
| **P5** | `Page` / `BBox` / `Image` (MinIO `s3://` link) moved into chunk metadata; crops uploaded under content-derived keys | `PDF_FIGURE_STORE` (off) | 89 (+1) | 244 |
| **P6** | `scripts/figure_eval.py` A/B harness + gold-figure template | none | 93 (+1) | 248 |

Checked by applying P0..P6 one at a time to a fresh copy of your zip: each patch applies, each phase's tests pass,
and **no existing test regressed at any step** (the ~32 tests that fail in my sandbox fail identically before any
patch because they need real Docling, which I stubbed). The final tree equals my working tree byte for byte.

### What each phase does and its "done when"

- **P0** Install before anything else, so the model downloads while the later phases are built. `start` returns at once; `status` shows percent; `verify` renders `SEM-IP ID1` into a PNG, asks the model to read it and checks `ID1` comes back. *Done when* `verify` prints `OK`.
- **P1** Behaviour-preserving. Tests run real PyMuPDF, because `pdf_cellmarks` swallows exceptions: a wrong import would silently switch tick/legend logic off. Every assertion is on a value the silent fallback cannot return. *Done when* no app file imports or references `fitz` (AST check) and the router exposes `pymupdf`.
- **P2** Per picture: geometry -> skip gate -> exact labels -> caption -> card. Dropped without any model call: tiny, sliver, inside a table, same image on 3+ pages, and classifier `logo/icon/photograph/signature/stamp/QR/barcode` with confidence >= 0.60 and no technical text. Unlisted or low-confidence classes are **read, never dropped**. A raster picture with no text layer and no caption produces **no card** (nothing deterministic to say). *Done when* image 5 (the Systevo front render) yields no chunk, a vector wiring diagram yields a `Figure:` card with its exact labels, and the dump has no `[Figure description]` and no bare class labels.
- **P3** Three or more similar, label-poor, non-technical panels with a short caption under each (line-level reading, row-major order, "Fig. N" caption grids rejected). *Done when* image 4's page gives one chunk with Steps 1..5 in order.
- **P4** The VLM never writes prose for the index. It returns JSON connections; each endpoint must be a contiguous token run inside **one** label line, exact match, endpoints never rewritten. This replaces the fuzzy `rapidfuzz` check from the earlier draft, which would accept `SBU ID2` for `SBU ID1` and then rewrite the endpoint. Per-request `keep_alive` (default 5m), `num_ctx` 4096, per-document call cap, errors never drop the card. *Done when* the A/B (section 4) clears the gate.
- **P5** Object key `figures/<sha1-prefix-of-file>/<figure_id>.png`, so no API change and re-ingest overwrites. The chunker strips the tail from embedded text into `figure_page`, `figure_bbox`, `figure_image`. *Done when* a figure chunk in Chroma carries `figure_image` and the object exists in MinIO.
- **P6** `list` finds figure boxes and shows which have a text layer; `run` scores models x {grounded, blind} on connection precision/recall and label recall, counting only validated connections.

## 3. Settings (all env vars, all additive)

| Env var | Default | Phase |
|---|---|---|
| `PDF_VLM_MODEL` | `qwen2.5vl:3b` | P0 |
| `PDF_FIGURE_PIPELINE` | `v5` (set `v6` to opt in) | P2 |
| `PDF_FIGURE_REPEAT_MIN_PAGES` / `PDF_FIGURE_TECH_REGEX` | `3` / built-in Honeywell tokens | P2 |
| `PDF_FIGURE_PROCEDURES` | `true` | P3 |
| `PDF_FIGURE_OCR` / `PDF_FIGURE_RENDER_DPI` | `false` / `200` | P4 |
| `PDF_VLM_ENABLED` / `_TIMEOUT` / `_MAX_PER_DOC` / `_KEEP_ALIVE` | `false` / `120` / `40` / `5m` | P4 |
| `PDF_FIGURE_STORE` / `PDF_FIGURE_STORE_PREFIX` | `false` / `figures` | P5 |

`PDF_FIGURE_MODE=off` still disables all cards. Rollback at any time: `PDF_FIGURE_PIPELINE=v5`.

## 4. Run it

**Step 0, today:** `docker compose up -d ollama`, then `python scripts/qwen_setup.py start` (returns immediately),
`python scripts/qwen_setup.py status` whenever you like, `python scripts/qwen_setup.py verify` when it is installed.
Pure-Docker alternative: `docker exec -d honeywell_ollama sh -c "ollama pull qwen2.5vl:3b > /tmp/pull.log 2>&1"`.
Make sure the Ollama image is recent enough for Qwen vision models (`docker compose pull ollama`).

**Apply in order:** `git apply --check v6_pN.patch` then `git apply v6_pN.patch` for N = 0..6, running
`pytest tests/parsing_arch/v6 -q` after each. (CRLF "trailing whitespace" warnings are expected.)

**Real-PDF check after P3:** set `PDF_FIGURE_PIPELINE=v6`, run `test_parse.py` on 89470K2 and check the dump:
no `[Figure description]`, no stand-alone class labels, no "home theater", step page = one `Procedure` chunk,
vector diagrams = `Figure:` cards with exact labels, repeated logos = nothing. The log shows skip reasons per page.

**Before enabling the VLM (P4/P6):** `python scripts/figure_eval.py list --pdf <manual.pdf> --pages 1-12` (`labels=0` on
a diagram means it is raster: use `PDF_FIGURE_OCR=true`), write ~12 gold figures from `scripts/gold_figures.template.json`,
then `python scripts/figure_eval.py run --pdf <manual.pdf> --gold <gold.json> --models qwen2.5vl:3b,qwen3-vl:2b > results.csv`.
**Gate:** kept-connection precision >= 0.9 and grounded clearly above blind; otherwise stay on labels (+ OCR).
Precision beats recall: a wrong wire in the index is worse than a missing one.

**Enable P5:** `PDF_FIGURE_STORE=true` with the minio service up. When everything is signed off, flip the default of
`pdf_figure_pipeline` to `"v6"` in `config.py` (one line).

## 5. Not verified, risks

Verified here: `docling-core` 2.102.0, PyMuPDF 1.28.2, real RapidOCR (slow test `pytest -m slow`), fake Ollama and fake S3 servers, synthetic PDFs, per-phase sequential patch application.

**Not run:** Docling's models, Ollama/Qwen, real MinIO/boto3, your PDFs, the Windows branch of the detached spawn (the POSIX branch ran end to end).
- `_build_figure_converter` mirrors your VLM converter options minus picture description; confirm table/OCR output on image pages is unchanged.
- The chunker's tail-to-metadata split is unit-tested; the full `HybridChunker` path is not.
- **Speed:** compose gives Ollama no GPU, so a 3B vision model on CPU may take minutes per diagram. If so: `docker-compose.gpu.yml` (untested on your machine) or `PDF_VLM_MODEL=qwen3-vl:2b`. Model sizes are from memory; check `ollama list`.
- Step-panel heuristics were tuned on a synthetic page; check them on the real Systevo installation page.
- OCR spaced forms make `DBUS2` match `DBUS 2`; unmatched connections are dropped (a safe failure), so a low kept-count can mean OCR noise, not a bad model.

**Differences from the earlier Gemini draft:** exact token match instead of `rapidfuzz`; PyMuPDF image digests instead of a 16x16 pHash; crops rendered from the PDF at 200 DPI instead of `images_scale=2.5`; pictures inside table cells are skipped (v5.9 cell-mark logic already covers ticks); the converter split is a new `_build_figure_converter`, so DOCX/PPTX are not touched.

**Deferred:** pictures and vector-only diagrams on text-routed pages (>= 800 chars of text never reach Docling; `page.cluster_drawings()` is the lever), expanding `[7]`-style callouts from the section's component list, presigned image display in answers, per-panel arrow descriptions, ColPali-style page retrieval.
