# v5.5 Patch Plan: Fix the Two Bugs Diagnostics A/B Isolated

**Branch:** `feat/pdf-deep-parser` (continues on v5.4)
**Scope:** `parsers/pdf_router.py` (`_repair_pdf_headings()`, new `_heading_level()` /
`_as_section_header()` helpers, Diagnostic A print widened), `core/chunker.py`
(Gap B synthetic-heading insertion point). No schema/route changes.
**Trigger:** v5.4's Diagnostic A/B output, captured from a real `test_parse.py`
run (see the pasted `HEADING ...` / `ORPHAN-CHECK ...` lines and the 128-chunk
dump attached to this session).

---

## What the diagnostics actually showed

**Diagnostic A (heading-level hypothesis) was answered, but not the way v5.4
guessed.** v5.4's hypothesis was that promoted numbered paragraphs all shared
one wrong default `level`. The real dump showed something different:
`"5.5 Mobility"` and `"7.10 Supercompensation"` — the two headings that
correctly clear the freeze — are the *only* two lines in the entire dump with
`level=1` and **no `level` attribute printed as a plain int for a
`SECTION_HEADER`**, because they aren't `SECTION_HEADER` at all. Re-running the
dump with the print widened to include `TITLE` (which v5.4's version silently
excluded) confirmed it: both are `TitleItem`s. pymupdf4llm re-derives its own
`'#'`/`'##'` mapping independently on every single-page conversion, so a
sub-section heading that happens to be the single largest font on its own
page comes out as `'# '` → `TitleItem`, which `HierarchicalChunker` keys at
level 0 — a slot only another `TitleItem` can clear. Every numbered heading in
between (7.1–7.9) is a `SECTION_HEADER` at level ≥ 1 and can never touch that
level-0 slot, which is exactly the freeze span reported in v5.2/v5.3/v5.4.

**Diagnostic B (list-order vs. traversal-order) confirmed traversal-order,**
matching v5.4's own reading of the flat-index evidence: the three orphans sit
at their correct positions in `doc.texts`. The actual cause is
`core/chunker.py`'s Gap B pass, which appends heading-only synthetic chunks
to the *end* of the output list regardless of their source page.

## Fix 1 — normalise every heading to a leveled `SectionHeaderItem`

`_repair_pdf_headings()`'s Pass 2 now rewrites **every** `TITLE` or
`SECTION_HEADER` item into a `SectionHeaderItem` with an explicit level:
numbered headings get their level from numbering depth (`"7.3"` → 2, `"7.3.1"`
→ 3); unnumbered headings default to level 1, never 0. No `TitleItem` survives
the pass, so nothing can occupy `HierarchicalChunker`'s level-0 slot by
accident.

## Fix 2 — insert Gap B synthetic chunks at page position, not at the tail

`core/chunker.py`'s heading-only-chunk loop now finds the first existing chunk
whose page is greater than the synthetic chunk's page and inserts there
(falling back to the end when there is no later page), then renumbers
`chunk_index` to match final list position.

## Validation

Reproduced both bugs offline against the installed `docling-core` (no
project-specific code needed to prove the mechanism): a synthetic 5-page
document with the same title/heading/text shape as the real PDF showed the
identical freeze, confirming the `TitleItem`-as-level-0 mechanism before
writing the fix. `tests/parsing_arch/v5_5/test_title_freeze_and_tail_order.py`
carries that repro plus end-to-end tests for the real fix (including a
`HybridChunker`-stand-in, since the real tokenizer needs a network fetch this
sandbox doesn't have).

## Known follow-ups (found by an external review of the fixed real-PDF run)

Fixing the mechanism above did not fix every symptom that looked like it —
several *different* causes produce the same "heading context wrong" symptom.
Deferred to v5.6 (see `docs/v5_6_plan.md`):
- Section numbers pymupdf4llm extracted out of position within the heading
  string ("Greasing 6.4 the Groove").
- An empty-text `TITLE`/`SECTION_HEADER` item, which this patch's Pass 2 skips
  via `if not stripped: continue` before ever reaching the normalisation
  step above — it keeps its raw (possibly level-0) level.
- Heading text duplicated as literal, un-parsed markdown syntax
  (`"### **7.1 Consistency**"`) glued onto the tail of the preceding
  paragraph.
- A handful of chapter headings pymupdf4llm never `'#'`-detected at all.
