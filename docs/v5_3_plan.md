# v5.3 Patch Plan: Picture-Description Cleanup Gap + Unifying the Heading/Ordering Bugs

**Branch:** `feat/pdf-deep-parser` (continues on v5.2)
**Scope:** `parsers/pdf_router.py` (one 2-line fix, `_smolvlm_page()`; one new
function, `_flatten_document()`). No changes to `docling_parser.py` or
`config.py` this round. `core/chunker.py` unchanged.
**Trigger:** Second live `test_parse.py` run, after v5.2 landed. Confirms
Fix 1 (VLM pipeline options) worked. Shows Fix 2 (heading repair) had **zero
measurable effect** — same freeze, same break point, chunk-for-chunk
identical to the pre-v5.2 run. That non-result is the actual finding this
patch is built on.

---

## How this was tested

Same real `test_parse.py` run pattern as v5.2 — actual `docling` + `pymupdf4llm`
+ `RapidOCR` + `SmolVLM` pipeline, full stdout captured, 121 chunks this time
(down from 124 pre-v5.2, consistent with `_repair_pdf_headings()`'s label
changes altering how `_merge_pages()`'s markdown re-parse segments text).

Two comparisons were made directly against the v5.2 log line-by-line:

1. Chunk #1's text now contains `"In this image there are two men standing
   and smiling."` — SmolVLM description text is present for the first time.
   Confirms Fix 1.
2. The heading freeze — `"5.5 Mobility"` present in every chunk's metadata
   context from chunk #28 through chunk #63 (pages 12–21), breaking only at
   chunk #64 (`"7.10 Supercompensation"`, page 21) — is **identical in span
   and break point** to the pre-v5.2 run. Fix 2 changed labels (visible: e.g.
   `"7.3 Train Systematically"` now appears in chunk text where it was
   plain-paragraph before) but changed nothing about which heading
   `HybridChunker` reports as active context.

---

## Issues found

### Issue 1 (Medium) — `_smolvlm_page()` skips the token-cleanup pass

**Root cause, confirmed against `pdf_router.py` lines 262–277:**
`_smolvlm_page()` calls `result.document.export_to_markdown()` directly.
`_picture_descriptions_only()` — the sibling function for table+image pages —
instead calls `_inject_picture_descriptions(doc)` first (`docling_parser.py`
line 307), which strips SmolVLM's raw completion tokens
(`re.sub(r"<[a-z_]{1,40}>", "", raw_text)` for complete tokens,
`re.sub(r"<[a-z_]{0,40}\s*$", "", cleaned)` for a dangling one cut off by
`max_new_tokens`) and tags the result `"[Figure description] ..."` before it
reaches the text stream. `_smolvlm_page()` never calls this, so its output
carries the raw model completion unmodified — visible in chunk #1:

```
In this image there are two men standing and smiling.<end_of_utteranc
```

That's exactly the "dangling token cut off before its closing `>`" case the
second regex in `_inject_picture_descriptions()` exists to catch — it's just
never invoked on this path. Two consequences: garbage token fragments leak
into chunk text on every image-only page, and — separately — image-only-page
descriptions aren't tagged `"[Figure description]"` the way table+image page
descriptions are, so a downstream consumer can't distinguish or filter VLM
captions consistently between the two tiers.

### Issue 2/4 (High) — same underlying mechanism, now with direct evidence they're linked

v5.2 treated the heading freeze (Issue 2) and the tail-ordering bug (Issue 4)
as separate, with Issue 2 "fixed" via label-swapping and Issue 4 deferred to
a test-first investigation. This run's non-result on Issue 2 changes that
picture.

**What the non-result actually shows:** `_repair_pdf_headings()` only
rewrites `item.label` (`PARAGRAPH` ↔ `SECTION_HEADER`) via the
`model_dump()`-swap pattern. It never touches `item.parent`. Chunk #56's text
— `"5.5 Mobility\n7.3 Train Systematically\n..."` — shows `7.3` *is* now
correctly labeled `SECTION_HEADER` (visible in the exported text) but is
still reported as nested *underneath* `5.5 Mobility` in
`chunk.meta.headings`. That's not a label problem — `HybridChunker` derives
`meta.headings` by walking each item's ancestor chain (via `item.parent`),
not by scanning for the most recent `SECTION_HEADER`-labeled item in list
order. A relabeled item with an unchanged, stale `parent` reference stays
nested exactly where it was.

That reframes Issue 4 too. `_merge_pages()`'s `combined.add_document(page_doc)`
(line 360) is the one place structure from independently-parsed per-page
documents gets threaded into a shared tree. If `add_document()` attaches each
new page's content as children of whatever group was structurally "open" in
`combined` at merge time — rather than as flat, page-independent top-level
content — that single mechanism explains **both** symptoms at once: headings
freeze because nesting persists page-to-page with nothing to close it out
early, and orphaned items land at the document tail because whatever
resolves group/parent boundaries during the merge pushes anything it can't
place cleanly to the end of a traversal. `"CALISTHENICS MYTHS & THE ANSWERS"`
(all-caps, page 22) correctly clearing the freeze is consistent with this —
it's the first item since page 12 unambiguous and structurally shallow
enough that whatever merge logic is doing closes out the stale ancestor.

This is a working hypothesis, not a confirmed trace through `docling_core`
internals (still can't cite a line there). But it's now supported by two
independent symptoms pointing at the same function, which is enough to
justify one unified fix attempt rather than two separate patches.

---

## Fixes

### Fix 1 — call the existing cleanup function (Issue 1)

Minimal, low-risk, reuses code that already exists and is already imported:

```python
# pdf_router.py — _smolvlm_page(), replace the try block's return
try:
    if self._vlm_converter is None:
        self._vlm_converter = _build_vlm_converter()
    stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
    doc = self._vlm_converter.convert(stream).document
    _inject_picture_descriptions(doc)          # NEW — was missing; _inject_picture_descriptions
    return doc.export_to_markdown()             # is already imported at the top of this file
except Exception as exc:
    ...
```

`_inject_picture_descriptions` is already in this file's import line
(`from .docling_parser import _build_vlm_converter, _inject_picture_descriptions`)
— it's imported but unused on this path today, so this is a two-line change
with no new dependency.

### Fix 2 — stop trusting `add_document()`'s structure; rebuild flat (Issues 2/4, unified)

Rather than patch `_repair_pdf_headings()` again to also fix `item.parent`
(which requires knowing the exact reparenting call for whatever
`docling_core` version is installed — brittle to guess at blind), rebuild the
merged document as a deliberately flat structure: every text item becomes a
direct child of the new document's `body`, in the order `combined.texts`
already lists them. This sidesteps needing to mutate `item.parent` directly
by reusing `doc.add_text(..., parent=...)` — the same public API
`_inject_picture_descriptions()` already relies on elsewhere in this
codebase, so it's a proven call shape, not a guess.

```python
# pdf_router.py — new function, called at the end of _merge_pages()
def _flatten_document(doc: DoclingDocument) -> DoclingDocument:
    """Rebuild a merged multi-page document with every text item as a flat,
    direct child of body — discarding whatever nesting add_document()
    produced while threading independently-parsed per-page sub-documents
    together (see v5.3 Issue 2/4).

    _merge_pages() has no real visual hierarchy to preserve in the first
    place — each page was reconstructed from plain markdown text, so nesting
    fidelity was already approximate. Flattening trades that approximate,
    occasionally-wrong nesting for a flat structure HybridChunker resolves
    unambiguously: each item's heading context is the nearest preceding
    body-level SECTION_HEADER, full stop — no stale ancestor can survive
    across a page boundary because there are no ancestors below body at all.
    """
    flat = DoclingDocument(name=doc.name)
    for item in doc.texts:
        new_item = flat.add_text(
            label=item.label,
            text=item.text,
            parent=flat.body,
        )
        new_item.prov = item.prov  # carry page provenance over verbatim
    return flat
```

```python
# pdf_router.py — _merge_pages(), last lines
    _repair_pdf_headings(combined)   # v5.2 — still needed: fixes labels first
    return _flatten_document(combined)   # v5.3 — then flatten structure
```

**This is explicitly a candidate, same caveat as v5.2's Fix 4 Step 2:**
`doc.add_text()`'s exact signature (whether it accepts `prov=` directly vs.
needing post-hoc assignment as shown, whether `parent=flat.body` is the
correct way to request "top-level child" for the installed `docling_core`
version) needs confirming against your actual environment — I don't have
that library installed here to verify call shapes. If `add_text()` rejects
one of these arguments, the fix is still the same *idea* (flatten via the
public text-insertion API rather than fighting `add_document()`'s merge
semantics) — just adjust the call to match what your installed version's
`add_text()` signature actually accepts.

**Why this one change is expected to fix both issues, not just one:** if the
hypothesis in Issue 2/4 is right — that `add_document()`'s nesting behavior
is the single shared cause — then bypassing it entirely for the final
structure (keep using it to get each page's items into `combined.texts` in
the right order, but discard the tree it built and rebuild flat) removes the
mechanism behind both symptoms in one step, rather than patching each
symptom separately. If the freeze clears on the next test run but orphaned
tail chunks persist (or vice versa), that's direct evidence the two issues
are *not* the same mechanism after all — informative either way, not a
wasted attempt.

---

## File ownership for this patch

| File | Action |
|---|---|
| `parsers/pdf_router.py` | [MODIFY] `_smolvlm_page()` — call `_inject_picture_descriptions()` (Fix 1); new `_flatten_document()`, called at end of `_merge_pages()` after `_repair_pdf_headings()` (Fix 2) |
| `parsers/docling_parser.py` | **no change** |
| `config.py` | **no change** |
| `core/chunker.py` | **no change** |
| `tests/parsing_arch/v5_3/test_smolvlm_caption_cleanup.py` | [NEW] |
| `tests/parsing_arch/v5_3/test_flatten_document.py` | [NEW] |
| `tests/parsing_arch/v5_2/test_heading_integrity.py` | keep — `_repair_pdf_headings()` still runs, still needed for label correctness even though it alone doesn't fix nesting |
| `tests/parsing_arch/v5_2/test_chunk_ordering.py` | update — rerun against `_flatten_document()`; this is where Issue 4's deferred test-first step actually resolves |

---

## New tests to add

**`tests/parsing_arch/v5_3/test_smolvlm_caption_cleanup.py`**

1. `test_smolvlm_page_strips_dangling_token` — mock the VLM converter to
   return a document whose picture has description text ending in a
   dangling token (e.g. `"...smiling.<end_of_utteranc"`); call
   `_smolvlm_page()`; assert the returned markdown contains no `<` token
   fragment and does contain the `"[Figure description]"` prefix.
2. `test_smolvlm_page_and_picture_descriptions_only_produce_consistent_tagging`
   — run both functions against equivalent mocked VLM output; assert both
   apply the same prefix/cleanup, closing the inconsistency Issue 1 flagged.

**`tests/parsing_arch/v5_3/test_flatten_document.py`**

3. `test_flatten_removes_nesting` — build a `DoclingDocument` where a
   `SECTION_HEADER` on "page 1" has a `PARAGRAPH` child nested under it, and
   a second `SECTION_HEADER` from "page 2" is (incorrectly, simulating the
   bug) nested under the first one too; run `_flatten_document()`; assert
   every item's parent is `flat.body` and both section headers are siblings,
   not ancestor/descendant.
4. `test_flatten_preserves_order_and_provenance` — assert `flat.texts` order
   matches input order exactly, and every item's `prov[0].page_no` survives
   the rebuild unchanged.
5. `test_heading_path_advances_across_pages_end_to_end` (carried over from
   v5.2, now run against the full `_repair_pdf_headings()` →
   `_flatten_document()` pipeline instead of `_repair_pdf_headings()` alone)
   — this is the test that actually tells us whether the freeze is fixed.
6. `test_chunk_order_matches_page_order` (carried over from v5.2's deferred
   Fix 4 Step 1, now run against `_flatten_document()`'s output) — this is
   where Issue 4 gets its real answer instead of staying deferred.

---

## Non-regression checklist

- [ ] `tests/v0.3/`, `tests/v0.4/` pass unchanged
- [ ] `tests/parsing_arch/v1/` through `v5_2/` pass unchanged (note: `v5_2/
      test_chunk_ordering.py` is expected to change status — was `xfail`,
      should now be re-evaluated against `_flatten_document()`, not left
      silently xpassing or xfailing without inspection)
- [ ] `core/chunker.py` diff is empty
- [ ] Manual spot-check: rerun `test_parse.py` against the same PDF; confirm
      chunk #1 no longer contains any `<[a-z_]*` token fragment
- [ ] Manual spot-check: scan printed `Metadata:` context for the full run;
      confirm no heading label spans more than its own numbered section's
      chunks (e.g. `"5.5"` never appears once a chunk has reported `"5.6"`
      or higher)
- [ ] Manual spot-check: confirm chunk order is monotonic in page number for
      the full 121-chunk run (or whatever count results) — this is the
      direct check for whether Fix 2 actually resolved Issue 4 as well
- [ ] If either heading freeze or tail-ordering persists after this patch,
      record which one specifically — that result rules out the shared-cause
      hypothesis for whichever symptom didn't clear, and scopes v5.4 to
      treat it as independent after all

---

## Watch item (not scoped as a fix this round)

Chunk covering `"8.5 Should I watch my food when doing calisthenics?"`
(page 23) extracted garbled this run —
`"Yes   t s S    s    se calisthenics as..."` — where it extracted cleanly
pre-v5.2. Nothing in v5.1 or v5.2 touched `_triage_page()` or the plain-text
extraction path, so this looks like triage or OCR nondeterminism unrelated to
this patch rather than a regression it caused. Flagging for awareness; not
investigating further until it either recurs consistently or another patch
happens to touch that code path anyway.
