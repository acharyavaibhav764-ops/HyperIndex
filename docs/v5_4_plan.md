# v5.4 Patch Plan: Revert the Regression, Instrument the Rest

**Branch:** `feat/pdf-deep-parser` (continues on v5.3)
**Scope:** `parsers/pdf_router.py` only. One real fix. Two read-only
diagnostic additions. Nothing else changes.
**Trigger:** v5.3's real-PDF run showed `_flatten_document()` deleted every
table in the document (confirmed regression) while producing zero measurable
change to the heading freeze or tail-ordering bugs it was written to fix
(confirmed by direct chunk-for-chunk comparison against v5.2's output).

**What's actually in this patch, honestly:**
- **Fix 1** is validated and ready to ship — it's a revert, not new code, so
  there's no new API surface to get wrong.
- **Diagnostics A and B** are *not* fixes. I don't have a validated fix for
  the heading freeze or the tail-ordering bug. I have two hypotheses, and I
  do not have a way to test either one without executing real `docling_core`
  code, which this sandbox cannot do (no network access; confirmed by
  attempting `pip install docling-core` and getting "no matching
  distribution"; `requirements.txt` pins `docling>=2.0.0` with no lockfile,
  so I don't even know your exact resolved version). Writing another patch
  against a hypothesis I can't test is exactly how the table-loss regression
  happened. So this round, instead of a third guess, I'm giving you
  read-only print statements that cost nothing to run and will tell us,
  from your next real `test_parse.py` run, which hypothesis (if either) is
  right — so v5.5 is built from evidence instead of another guess.

---

## How the revert was validated (no execution required)

Controlled comparison, one variable changed, three real runs already in hand:

| Run | `_repair_pdf_headings()` | `_flatten_document()` | Tables present | Heading freeze (5.5→7.10) | Tail orphans |
|---|---|---|---|---|---|
| v5.2 | yes | no | **yes** | yes | 2 |
| v5.3 | yes | yes | **no** | yes (identical span) | 5 (see note below) |

Only `_flatten_document()` differs between those rows. It correlates 1:1 with
the table loss and correlates with *no* change to either bug it targeted.
That's sufficient to validate "remove it" without running anything — the
evidence is the three transcripts you already collected, not a new test I
ran.

**Note on the orphan count going from 2 to 5:** two of the three new v5.3
orphans — `"Animal Protein"` and `"Vegetarian Protein"` (page 27) — are very
likely a *side effect* of the table-loss bug, not a new instance of the
ordering bug: with their tables deleted, those caption lines had nothing
left to merge into and became degenerate standalone chunks that happened to
land at the tail. Once Fix 1 restores the tables, expect those two specific
orphans to disappear on their own — but that's a prediction to confirm from
your next run, not something I'm asserting as fact. The third new orphan,
`"CONTENTS"` (page 3), is different: it had `page: None` in every prior run
(no page number at all), so it was previously *impossible* to tell if it was
mis-ordered. Now that page-stamping works well enough to give it `page: 3`,
we can see for the first time that it's also stuck at the tail — this reads
as confirming evidence for the pre-existing Issue 4, not a new bug.

---

## Fix 1 (validated) — revert `_flatten_document()`

```python
# pdf_router.py — _merge_pages(), last two lines
    _repair_pdf_headings(combined)
    return combined                    # was: return _flatten_document(combined)
```

Leave the function in the file, unused, so the next person doesn't have to
reconstruct why it was tried:

```python
def _flatten_document(doc: DoclingDocument) -> DoclingDocument:
    """v5.3 candidate, reverted in v5.4.

    Only walked doc.texts — doc.tables was never touched, so every table in
    the document was silently dropped on the real PDF smoke test. It also
    had zero measurable effect on the heading freeze or tail-ordering bugs
    it was written to fix (confirmed by direct before/after chunk
    comparison), so even a corrected version that also handled tables
    would not have been worth the added complexity. Kept here for
    reference; do not re-enable without new evidence that reparenting is
    actually the mechanism behind either bug.
    """
    ...  # unchanged body, not called anywhere
```

Nothing else changes. `_repair_pdf_headings()` stays exactly as in v5.2/v5.3
— it's independently useful for label correctness even though it doesn't
resolve the freeze, and reverting it too would be an unrelated regression
with no evidence behind it.

---

## Diagnostic A — settle the heading-level hypothesis

**The hypothesis (unverified):** `_repair_pdf_headings()` promotes a
`PARAGRAPH` to `SECTION_HEADER` via `SectionHeaderItem(**item.model_dump())`.
A plain paragraph's `model_dump()` has no `level` key, so every promoted
heading likely gets whatever `SectionHeaderItem.level` defaults to —
possibly the *same* default for every promoted heading regardless of its
actual depth (7.1, 7.2, 7.3 all identical), while `"5.5 Mobility"` — detected
naturally by pymupdf4llm's own heading syntax — may carry a different,
real level. If `HybridChunker` resolves heading context by level rather
than by tree position, this would explain why the freeze persists across
every promoted heading (7.1–7.9) but clears exactly at `"7.10
Supercompensation"` (also naturally detected, not promoted).

This is a hypothesis, not a conclusion — I have no way to check
`SectionHeaderItem`'s actual default here.

```python
# pdf_router.py — _merge_pages(), immediately after _repair_pdf_headings(combined)
    if settings.pdf_debug_heading_dump:
        for item in combined.texts:
            if item.label == DocItemLabel.SECTION_HEADER:
                text_preview = (item.text or "")[:40]
                level = getattr(item, "level", "<no level attr>")
                page_no = item.prov[0].page_no if item.prov else None
                logger.info(
                    "HEADING page=%s level=%s text=%r",
                    page_no, level, text_preview,
                )
```

```python
# config.py — new setting, default off so this never runs in production
pdf_debug_heading_dump: bool = bool(int(os.getenv("PDF_DEBUG_HEADING_DUMP", "0")))
```

Run with `PDF_DEBUG_HEADING_DUMP=1 py test_parse.py <pdf>` and paste back
just the `HEADING ...` lines — not the full chunk dump. Specifically I need
to see the `level` value for `"5.5 Mobility"`, any one of `"7.1"`–`"7.9"`,
and `"7.10 Supercompensation"`. Three numbers settle this either way: if
they're all identical, the level hypothesis is wrong and we look elsewhere;
if the promoted ones share a value that differs from both naturally-detected
headings, that's the mechanism and the real fix is to set `level` explicitly
during promotion to match its numbering depth (e.g. `"7.3"` → same level as
`"5.5"`, since both are single-decimal subsections).

## Diagnostic B — settle whether the ordering bug is list-order or traversal-order

**The open question this closes:** does `combined.texts` (the flat list
attribute) already contain the three known orphans (`"Advanced Circuit"`,
`"CONTENTS"`, the `FULLJOURNEY25` code line) out of position — meaning
`add_document()`'s *list-append* order is wrong — or is the flat list
actually fine and something later (tree-based traversal in
`export_to_markdown()` or `HybridChunker`) is what reorders them for output?
These have different fixes: the first needs a change in how
`_merge_pages()` appends items; the second needs a change in how the
document is traversed for chunking, which is a much bigger, more
speculative change I don't want to attempt without knowing it's actually
necessary.

```python
# pdf_router.py — _merge_pages(), same debug block as Diagnostic A
    if settings.pdf_debug_heading_dump:
        total = len(combined.texts)
        for idx, item in enumerate(combined.texts):
            text_preview = (item.text or "")[:30]
            if any(marker in text_preview for marker in ("Advanced Circuit", "CONTENTS", "FULUOURIMEY", "Animal Protein")):
                page_no = item.prov[0].page_no if item.prov else None
                logger.info(
                    "ORPHAN-CHECK index=%d/%d page=%s text=%r",
                    idx, total, page_no, text_preview,
                )
```

If these indices come back near the *end* of the `0..total` range despite
their `page_no` values being 3, 17, and 32 (i.e., they're genuinely last in
the flat list, not just last after some later reordering step), that
confirms the bug is in `_merge_pages()`'s append order itself — likely in
how `add_document()` sequences items from a page whose markdown produced an
unusual shape (a heading-less table caption with no surrounding paragraph,
matching the real page 17 and page 32 content). If instead their list index
roughly matches their page position but they still print last in the actual
`test_parse.py` chunk output, the bug is downstream of `doc.texts` entirely,
in whatever `HybridChunker` or `export_to_markdown()` does with the tree —
a materially different and larger fix.

---

## File ownership for this patch

| File | Action |
|---|---|
| `parsers/pdf_router.py` | [MODIFY] `_merge_pages()` — revert return value (Fix 1); add gated diagnostic block (Diagnostics A+B); `_flatten_document()` kept but unused, comment updated |
| `config.py` | [MODIFY] add `pdf_debug_heading_dump` (default off — zero runtime cost when disabled, so this is safe to leave merged) |
| `parsers/docling_parser.py` | **no change** |
| `core/chunker.py` | **no change** |
| `tests/parsing_arch/v5_4/test_flatten_reverted.py` | [NEW] |

---

## New tests to add

**`tests/parsing_arch/v5_4/test_flatten_reverted.py`**

1. `test_merge_pages_does_not_call_flatten` — spy/mock `_flatten_document`;
   run `_merge_pages()` against a fixture with a table; assert
   `_flatten_document` is never called and the returned document's
   `doc.tables` is non-empty. This is the direct regression test for the
   bug this patch fixes — it would have caught v5.3's issue before it ever
   reached a real PDF.
2. `test_debug_heading_dump_default_off` — assert `settings.pdf_debug_heading_dump`
   defaults to `False`/`0` and that no `HEADING`/`ORPHAN-CHECK` log lines are
   emitted from `_merge_pages()` when it's unset, so this diagnostic can't
   leak into production logs by accident.

I'm not adding tests for the heading-level or list-order hypotheses
themselves — there's nothing to assert yet. Once Diagnostic A/B's real
output comes back, the actual fix and its test get written together, against
real numbers instead of a guess.

---

## Non-regression checklist

- [ ] `tests/v0.3/`, `tests/v0.4/` pass unchanged
- [ ] `tests/parsing_arch/v1/` through `v5_3/` pass unchanged
- [ ] `core/chunker.py` diff is empty
- [ ] `parsers/docling_parser.py` diff is empty
- [ ] Manual spot-check: rerun `test_parse.py` against the same PDF with
      `PDF_DEBUG_HEADING_DUMP` unset (default) — confirm chunk count returns
      to ~121 (not 104), confirm `"Animal Protein"` / `"Vegetarian Protein"`
      chunks contain their table rows again, confirm no diagnostic log lines
      appear
- [ ] Rerun with `PDF_DEBUG_HEADING_DUMP=1` — capture and paste back the
      `HEADING ...` and `ORPHAN-CHECK ...` lines only
- [ ] Do **not** attempt a fix for the heading freeze or tail-ordering bug
      based on this patch alone — that's explicitly deferred to v5.5, once
      Diagnostic A/B output is in hand
