# v5.2 Patch Plan: PDF VLM Pipeline-Options Fix + Cross-Page Heading Integrity

**Branch:** `feat/pdf-deep-parser` (continues on top of v5.1, same branch — patch, not a
new integration point)
**Scope:** `parsers/docling_parser.py` (primary, one function), `parsers/pdf_router.py`
(new heading-repair pass + one-line fallback fix), `config.py` (one new setting).
No public API, schema, or route changes. `core/chunker.py` requires zero changes.
**Trigger:** Live end-to-end run of `test_parse.py` against a real multi-page PDF
after v5.1 was reported complete. v5.1 fixed page-provenance and triage
calibration correctly — this patch fixes two things v5.1 didn't touch: the PDF
picture-description pipeline never actually running, and heading context
corrupting itself across pages.

---

## How this was tested

v5.1's own fixes were verified as landed and correct by reading the current
`parsers/pdf_router.py` / `parsers/docling_parser.py` / `config.py` directly:
`_merge_pages()` does stamp `prov` per page, `_triage_page()` returns
`list[str]`, `config.py` has `pdf_min_text_chars_for_text_route`. Good.

What surfaced the two new issues below was a **real** `test_parse.py` run
against a full multi-page PDF (not the offline `docling-core`-only
reproduction v5.1 used) — actual `pymupdf4llm` + `docling` + `RapidOCR` +
`SmolVLM` in the loop, stdout captured in full. Two things stood out
immediately in that log and were then traced to exact lines:

```
SmolVLM failed for page 0 of <file>.pdf: 'ConvertPipelineOptions' object has
no attribute 'generate_page_images'. Falling back to PyMuPDF4LLM.
...
Picture description failed for page 2 of <file>.pdf: 'ConvertPipelineOptions'
object has no attribute 'generate_page_images'. Keeping table content;
skipping image description for this page.
```

— on every single page that hit the image or table+image tier, with no
exceptions. Separately, comparing the resulting chunk stream's
`chunk.meta.headings` context against the source PDF's actual section
numbering showed the heading path freezing on `"5.5 Mobility"` for ~35
consecutive chunks spanning pages 13–19, and later chunks picking up the
page footer (`"Calisthenics Family | Calisthenics Training Guide"`) as if it
were a heading.

---

## Issues found

### Issue 1 (Critical) — v5.1 Fix 4a wired PDF into the VLM converter with the wrong options class

**Root cause, confirmed against the log above:** `_build_vlm_converter()`
(`docling_parser.py`, current lines 93–105) constructs a single
`ConvertPipelineOptions` instance and hands the *same* instance to all three
format options:

```python
pipeline_options = ConvertPipelineOptions(
    do_picture_classification=True,
    do_picture_description=True,
    picture_description_options=picture_opts,
)
return DocumentConverter(format_options={
    InputFormat.DOCX: WordFormatOption(pipeline_options=pipeline_options),
    InputFormat.PPTX: PowerpointFormatOption(pipeline_options=pipeline_options),
    InputFormat.PDF:  PdfFormatOption(pipeline_options=pipeline_options),  # v5.1 Fix 4a
})
```

`ConvertPipelineOptions` is the generic/simple-pipeline options class — correct
for DOCX/PPTX. The PDF backend needs `PdfPipelineOptions`, the PDF-specific
subclass that carries `generate_page_images`, OCR options, and table-structure
options. `ConvertPipelineOptions` has none of those fields. v5.1 Fix 4a added
the `InputFormat.PDF` entry (correctly diagnosing that it was missing) but
reused the wrong options object to do it, so every SmolVLM call against a PDF
page throws the `AttributeError` shown above, is caught by the existing
`except Exception` blocks in `_smolvlm_page()` and `_picture_descriptions_only()`,
and silently degrades — meaning **v5.1's entire Fix 4 feature (table+image
merge, image-tier VLM descriptions) has never actually run once** since it
landed. It always takes the fallback branch. No test in `tests/parsing_arch/v5_1/`
caught this because that suite mocks the converter rather than exercising the
real `docling` PDF pipeline — reasonable given the sandbox's install
constraints noted in the v5.1 doc, but it means this class of bug is
untestable offline and needs one real-pipeline smoke test (see below).

### Issue 2 (High) — heading context corrupts itself across pages

**Root cause:** `_merge_pages()` converts each page's markdown into a
`DoclingDocument` **independently** (`DocumentConverter(allowed_formats=[InputFormat.MD])`
called fresh per page, current lines ~343–360) before stamping `prov` and
merging. Heading classification (which lines become `SECTION_HEADER` vs plain
paragraph) is redecided from scratch per page by whatever markdown the source
extractor (`pymupdf4llm` or Docling's own export) happened to produce for that
page. There is no cross-page consistency check. Two failure modes follow
directly from this, both observed in the real run:

- A real section heading that doesn't happen to render with heading syntax on
  its own page is silently demoted to a plain paragraph. `HybridChunker`'s
  `chunk.meta.headings` then keeps whatever the *last successfully promoted*
  heading was — in the test run, `"5.5 Mobility"` — as the active context for
  every chunk until the next thing that *does* get promoted, dragging that
  stale label through ~35 unrelated chunks (sections 5.6 through 7.3).
- Short, unpunctuated, repeating text — specifically the running page footer
  — is exactly the shape a per-page, font-size-only heading heuristic
  misfires on. Once it clears that bar on any one page, it starts appearing
  in `chunk.meta.headings` for chunks on that page and after.

Note this is a different bug from Issue 1 in v5.1 (which was about `prov`
being `[]`, not about heading labels) — v5.1's fix stamps page numbers
correctly but does not touch heading classification, so this was present
before v5.1 too and is only now visible because page numbers are finally
trustworthy enough to localize it.

`_promote_pptx_pseudo_headings()` (`docling_parser.py`) already solves a
sibling problem for PPTX — promoting short, non-period-ending first-items on
a slide to `SECTION_HEADER` — but it's gated to `.pptx` only and has no
demotion counterpart for repeated boilerplate. There is currently no
equivalent pass for PDF output at all.

### Issue 3 (Low) — image-tier VLM calls don't respect `enable_picture_description`

`_smolvlm_page()` and `_picture_descriptions_only()` (`pdf_router.py`) call
`_build_vlm_converter()` unconditionally. `docling_parser.py`'s own DOCX/PPTX
path gates VLM use behind `settings.enable_picture_description` (`parse()`,
line 277); the PDF router doesn't check it at all. Arguably intentional today
— an "image" route exists specifically to get a description — but it means
setting `ENABLE_PICTURE_DESCRIPTION=false` has no effect on PDF ingestion
while silently disabling it for DOCX/PPTX, which is a surprising asymmetry
worth closing while Issue 1 is already touching this function.

### Issue 4 (Medium) — orphaned items land at the document tail, out of page order

**Observed, root cause not yet confirmed:** in the same real run, two chunks
that belong on pages 17 and 32 (a stray table-caption fragment and an
isolated code-line) were emitted as the very last two chunks of the entire
124-chunk output — after content from every later page, including page 36.
`_merge_pages()`'s per-page loop (`for page_no, md in enumerate(page_markdowns,
start=1): ... combined.add_document(page_doc)`) appends `page_markdowns` in
strict page order, so the bug isn't in this repo's loop ordering — it points
at `DoclingDocument.add_document()` (inside `docling_core`, not this
codebase) not preserving position for items that come out of a per-page
markdown parse as parentless/floating nodes (e.g. a markdown fragment with no
enclosing paragraph or list context). That's a plausible mechanism, not a
confirmed one — there's no line in `docling_core` to cite for it yet.

Given v5.1's own experience with Issue 1 above (a real-pipeline behavior no
mocked test caught), the right move here is **test-first**: add a regression
test that asserts page-order monotonicity end-to-end, which will fail
reliably today regardless of the exact internal cause, then decide the fix
based on what it shows rather than guessing at `docling_core` internals now.

---

## Fixes

### Fix 1 — give the PDF format option real `PdfPipelineOptions` (Issue 1)

```python
# docling_parser.py — _build_vlm_converter()
from docling.datamodel.pipeline_options import (
    ConvertPipelineOptions,
    PdfPipelineOptions,              # NEW
    PictureDescriptionVlmEngineOptions,
)

def _build_vlm_converter() -> DocumentConverter:
    ...
    pipeline_options = ConvertPipelineOptions(
        do_picture_classification=True,
        do_picture_description=True,
        picture_description_options=picture_opts,
    )
    # PDF needs its own options class — ConvertPipelineOptions has no
    # generate_page_images / OCR / table-structure fields, which is exactly
    # what SmolVLM's PDF page-rasterization path reads.
    pdf_pipeline_options = PdfPipelineOptions(
        do_picture_classification=True,
        do_picture_description=True,
        picture_description_options=picture_opts,
        generate_page_images=True,   # required so the VLM has a rasterized page to see
    )

    return DocumentConverter(
        format_options={
            InputFormat.DOCX: WordFormatOption(pipeline_options=pipeline_options),
            InputFormat.PPTX: PowerpointFormatOption(pipeline_options=pipeline_options),
            InputFormat.PDF:  PdfFormatOption(pipeline_options=pdf_pipeline_options),  # FIXED
        }
    )
```

Also apply the `enable_picture_description` gate here (Fix 3, folded in since
it's the same function): early-return a plain `DocumentConverter()` if the
setting is off, matching `DoclingParser.parse()`'s existing behavior — avoids
building a VLM converter PDF callers can't use anyway.

### Fix 2 — repair heading integrity after merge (Issue 2)

New pass, run once against the fully merged document (needs all pages present
to detect cross-page repetition), called at the end of `_merge_pages()`
before `combined` is returned:

```python
# pdf_router.py
import re
from collections import Counter
from docling_core.types.doc import TextItem, SectionHeaderItem

_NUMBERED_HEADING_RE = re.compile(r"^\d+(\.\d+){0,3}\s+\S")  # "7.6 Specificity", "9.4.2 Proteins"

def _repair_pdf_headings(doc: DoclingDocument, min_page_repeats: int | None = None) -> None:
    """Fix heading fidelity lost by _merge_pages()'s per-page independent
    markdown parsing (see v5.2 Issue 2).

    Two passes:
    1. Demote boilerplate — any text appearing verbatim on
       >= min_page_repeats distinct pages is a running header/footer, not a
       heading. Demote it wherever a per-page heuristic mistagged it as
       SECTION_HEADER/TITLE, so it never enters chunk.meta.headings.
    2. Promote numbered headings — any PARAGRAPH matching the document's own
       "N.N[.N[.N]] <text>" numbering is promoted to SECTION_HEADER even if
       the per-page markdown heuristic missed it, so HybridChunker's heading
       path advances instead of staying frozen on the last lucky promotion.

    Mirrors the model_dump()-swap technique already used in
    _promote_pptx_pseudo_headings() for the sibling PPTX problem.
    """
    min_page_repeats = min_page_repeats or settings.pdf_boilerplate_min_page_repeats

    pages_seen_on: dict[str, set[int]] = {}
    for item in doc.texts:
        stripped = (item.text or "").strip()
        page_no = item.prov[0].page_no if getattr(item, "prov", None) else None
        if stripped and page_no is not None:
            pages_seen_on.setdefault(stripped, set()).add(page_no)

    boilerplate = {t for t, pages in pages_seen_on.items() if len(pages) >= min_page_repeats}

    for i, item in enumerate(doc.texts):
        stripped = (item.text or "").strip()
        if not stripped:
            continue

        if item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE) and stripped in boilerplate:
            dump = item.model_dump()
            dump["label"] = DocItemLabel.PARAGRAPH
            doc.texts[i] = TextItem(**dump)
            continue

        if (
            item.label == DocItemLabel.PARAGRAPH
            and len(stripped) < 100
            and _NUMBERED_HEADING_RE.match(stripped)
        ):
            dump = item.model_dump()
            dump["label"] = DocItemLabel.SECTION_HEADER
            doc.texts[i] = SectionHeaderItem(**dump)
```

```python
# config.py — new setting
pdf_boilerplate_min_page_repeats: int = int(os.getenv("PDF_BOILERPLATE_MIN_PAGE_REPEATS", "3"))
```

```python
# pdf_router.py — _merge_pages(), last line
    _repair_pdf_headings(combined)
    return combined
```

The numbering regex is generic to the source doc's own convention (`N.N`,
`N.N.N`) rather than hardcoded to this test PDF, so it should generalize to
Honeywell manuals that follow standard technical-doc section numbering; it
will need a quick check against a real Honeywell manual's numbering style
once this lands, same spirit as v5.1's "tune once this lands" note on the
800-char threshold.

### Fix 3 — folded into Fix 1 above (Issue 3)

### Fix 4 — diagnose, then fix, tail-ordering (Issue 4)

Step 1 (this patch): land `test_chunk_order_matches_page_order` (below) so
the failure is pinned down precisely — which stage introduces the reorder —
rather than guessed at.

Step 2 (follow-up, scoped once Step 1's failure output is in hand): if the
test confirms `combined.add_document(page_doc)` is where order is lost, stop
relying on it for merging and instead splice each `page_doc`'s items directly
onto `combined` in the loop's own order:

```python
# pdf_router.py — _merge_pages(), candidate fallback if add_document() is confirmed at fault
for page_no, md in enumerate(page_markdowns, start=1):
    ...
    page_doc = converter.convert(stream).document
    for item in page_doc.texts:
        item.prov = [ProvenanceItem(...)]
    combined.texts.extend(page_doc.texts)      # explicit order, no add_document() reshuffle
    combined.tables.extend(page_doc.tables)
    combined.pictures.extend(page_doc.pictures)
```

This is marked "candidate" rather than committed because it bypasses whatever
bookkeeping `add_document()` does beyond appending (parent/child refs,
`self_ref` fixups) — needs verifying those still resolve correctly for
`HybridChunker` before it replaces the current call, not just that ordering
improves.

---

## File ownership for this patch

| File | Action |
|---|---|
| `parsers/docling_parser.py` | [MODIFY] `_build_vlm_converter()` — use `PdfPipelineOptions` for the PDF format option (Fix 1), gate on `enable_picture_description` (Fix 3) |
| `parsers/pdf_router.py` | [MODIFY] new `_repair_pdf_headings()` (Fix 2), one call added at the end of `_merge_pages()`; Fix 4 Step 2 (candidate) held for follow-up pending Step 1's test result |
| `config.py` | [MODIFY] add `pdf_boilerplate_min_page_repeats` |
| `core/chunker.py` | **no change** |
| `tests/parsing_arch/v5_2/test_vlm_pdf_pipeline_options.py` | [NEW] |
| `tests/parsing_arch/v5_2/test_heading_integrity.py` | [NEW] |
| `tests/parsing_arch/v5_2/test_chunk_ordering.py` | [NEW] |
| `tests/parsing_arch/v5_1/test_page_provenance.py` | unchanged — still valid, orthogonal to this patch |

`tests/v0.3/`, `tests/v0.4/`, and `tests/parsing_arch/v5/` are untouched.

---

## New tests to add

**`tests/parsing_arch/v5_2/test_vlm_pdf_pipeline_options.py`**

1. `test_build_vlm_converter_pdf_uses_pdf_pipeline_options` — call
   `_build_vlm_converter()`, inspect `converter.format_options[InputFormat.PDF]
   .pipeline_options`, assert `isinstance(..., PdfPipelineOptions)` and
   `generate_page_images is True`. This is the direct regression test for
   Issue 1 — a type check, no real model inference needed, so it runs offline.
2. `test_build_vlm_converter_pdf_options_independent_of_docx_options` — assert
   the PDF and DOCX entries are *not* the same object identity, guarding
   against a future refactor reintroducing the shared-instance bug.
3. `test_smolvlm_page_respects_enable_picture_description` — with
   `settings.enable_picture_description=False` (monkeypatched), assert
   `_smolvlm_page()` never calls `_build_vlm_converter()` (mock/spy) and goes
   straight to the PyMuPDF4LLM path.
4. `test_smolvlm_pdf_pipeline_smoke` (marked `@pytest.mark.slow` /
   `requires_gpu`, skipped in CI without the model weights available) — the
   one real-pipeline test: convert a one-page image-only PDF fixture through
   the actual `_build_vlm_converter()` PDF path and assert no `AttributeError`
   is raised and at least one `[Figure description]` CAPTION item is produced.
   This is the test class Issue 1 shows is missing — everything else in the
   v5.1/v5.2 suites mocks the converter, which is exactly why this bug shipped
   unnoticed.

**`tests/parsing_arch/v5_2/test_heading_integrity.py`**

5. `test_repeated_footer_demoted_from_headings` — build a `DoclingDocument`
   with the same short string tagged `SECTION_HEADER` on 5 different pages
   (simulating a running footer) plus real distinct headings elsewhere; run
   `_repair_pdf_headings()`; assert the footer string is now `PARAGRAPH` on
   every occurrence and does not appear in any `HybridChunker` chunk's
   `meta.headings`.
6. `test_numbered_paragraph_promoted_to_heading` — a `PARAGRAPH` item reading
   `"7.6 Specificity"` with no other change; run `_repair_pdf_headings()`;
   assert it's now `SECTION_HEADER`.
7. `test_heading_path_advances_across_pages_end_to_end` — feed a multi-page
   fixture through `_merge_pages()` (with Fix 2 applied) into
   `Chunker._split_docling()`; assert the sequence of `chunk.meta.headings`
   across the resulting chunks is non-decreasing in section number (e.g.
   never sees `"5.5"` again after a chunk has already reported `"7.1"`) —
   this is the end-to-end regression test for the exact freeze observed in
   the real run.
8. `test_boilerplate_threshold_respects_config` — same as test 5 but with
   `pdf_boilerplate_min_page_repeats=10` and only 5 repeats; assert the
   footer is *not* demoted, confirming the setting is actually read.

**`tests/parsing_arch/v5_2/test_chunk_ordering.py`**

9. `test_chunk_order_matches_page_order` — build a multi-page fixture where
   at least one page's markdown contains a parentless/floating fragment
   (a table caption with no enclosing block, mirroring the real chunk
   #123/#124 case); run it through `_merge_pages()` → `Chunker._split_docling()`;
   assert the resulting chunks' `page`/`page_numbers` values are
   non-decreasing across the whole list. This is expected to **fail on current
   code** — that failure's traceback/output is what Fix 4 Step 2 is scoped
   against.
10. `test_add_document_preserves_item_order` — narrower unit test isolating
    just `DoclingDocument.add_document()`: build two tiny single-page
    documents where one has a normal paragraph and the other has a
    parentless text item, merge them, and assert `combined.texts` order
    matches insertion order. Pinpoints whether Issue 4 is in `add_document()`
    itself or introduced earlier (e.g. by the per-page `InputFormat.MD`
    conversion producing the floating node in the first place).

---

## Non-regression checklist

- [ ] `tests/v0.3/`, `tests/v0.4/` pass unchanged
- [ ] `tests/parsing_arch/v1/` through `v5_1/` pass unchanged
- [ ] `POST /api/v1/documents` response schema, status codes unchanged
- [ ] `core/chunker.py` diff is empty
- [ ] Manual spot-check: run `test_parse.py` against a real multi-page PDF
      containing at least one image-only page and one table+image page;
      confirm the log no longer shows
      `'ConvertPipelineOptions' object has no attribute 'generate_page_images'`
      anywhere, and at least one printed chunk's text contains
      `[Figure description]`
- [ ] Manual spot-check: for the same run, scan the printed `Metadata:` lines'
      `headings`/context and confirm no single heading label persists across
      more than one document section's worth of chunks, and no running
      header/footer text appears as a heading
- [ ] `test_chunk_order_matches_page_order` result recorded even if still
      failing — Fix 4 Step 2 is deliberately deferred pending its output, not
      silently dropped; do not close this patch without either a passing test
      or an explicit follow-up ticket referencing it
