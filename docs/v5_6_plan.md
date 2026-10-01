# v5.6 Patch Plan: Three More Causes Behind the Same Symptom

**Branch:** `feat/pdf-deep-parser` (continues on v5.5)
**Scope:** `parsers/pdf_router.py` only — new regexes, one rewritten branch in
`_repair_pdf_headings()`'s Pass 2, two new helper functions
(`_extract_misplaced_number()`, `_split_embedded_headings()`), `_as_section_header()`
gains an optional `text=` override. No schema/route/config changes, no changes
to `core/chunker.py` or `docling_parser.py`.
**Trigger:** An external review of a full real-PDF run made against the v5.5
patch (128 chunks, `PDF_DEBUG_HEADING_DUMP=1` output attached). v5.5 fixed
exactly the two bugs Diagnostics A/B were built to isolate — confirmed: the
review found no remaining instance of the *specific* 5.5→7.10 freeze span or
of a chunk out of page order anywhere in the 128-chunk output. What it did
find is three narrower, mechanically distinct bugs that produce the same
surface symptom ("heading context looks wrong").

---

## What's actually in this patch, honestly

Same posture as v5.4/v5.5: each fix below is validated against a reproduction
built from the *actual strings* in the review and the real diagnostic dump —
not against a hypothesis. Where a fix is a narrower heuristic with real
false-positive risk (Fix D), the code and this doc say so explicitly, and it's
scoped as small as it can be while still covering the cited case.

**Not attempted here** — flagged, not silently dropped:
- CTA/bullet text mis-detected as a heading with no decidable textual marker
  (`"Become a Master of Your Own Bodyweight"`, `"Get The Program"`,
  `"r Transform Now"`). Two of the review's cited cases *do* have a decidable
  marker (`"Start Your Journey Now!"` ends in `!`; `"> Beginner Calisthenics
  Program"` starts with a blockquote marker) but several don't, and a
  heuristic that only catches some of them while silently missing others in
  the same category isn't worth the false-positive risk it adds elsewhere in
  the document. Needs either a font-size/boldness signal Docling's already
  discarded by this stage, or a hand-maintained deny-list — both bigger
  changes than this patch's scope.
- Table bugs: the duplicated Advanced/Beginner circuit tables (#53/#54
  identical), column-group mis-keying (protein tables, fats table), header
  row treated as data (5.7 weekly table, contents page, core circuit).
  Entirely different subsystem (Docling's table structure extraction /
  `HybridChunker`'s table serializer), not a heading-ordering bug.
- OCR/text-corruption (`"perlOOg"`, lost spaces, scrambled carb values,
  `"nut t t nts"`) and the mojibake (already established as a console-encoding
  artifact in the review, not a real bug).
- `"Apply The 8 80/20 Rule 66"` — its real `"9.9"` numbering isn't present
  anywhere in the extracted text (see Fix A below for why this specific case
  can't be recovered).

---

## Fix A — relocate a section number pymupdf4llm extracted out of position

**The bug:** `_heading_level()` (from v5.2/v5.5) only ever looks at a
heading's *first word* to detect numbering. When pymupdf4llm's per-page
extraction puts the section number somewhere other than the front —
`"Greasing 6.4 the Groove"`, `"Circuit t Training 6.5"`, `"Strength & Skill
Routine 5.7"`, `"Chest Circuit 6.5.1"`, `"Hydration 9.6"` — that check finds
nothing and falls back to a flat, undifferentiated level 1 for all of them,
which is exactly what the real diagnostic dump shows.

**The fix:** `_extract_misplaced_number(text)` searches the *whole* string for
a dotted number token. If exactly one is found and it isn't already leading,
the string is rewritten with the number moved to the front and the level is
derived from its dot count, same convention as the existing leading-number
path (`"N.N"` → level 2, `"N.N.N"` → level 3). Zero or multiple candidates
return `None` and the text is left untouched — this is why
`"Apply The 8 80/20 Rule 66"` isn't touched: `"66"` has no dot, so it never
matches the candidate pattern at all, and there's no dotted number anywhere
else in the string to relocate. Its real section number appears to be lost
upstream of anything this pass can see; recovering it would mean cross-
referencing the table of contents against page numbers, well outside a
heading-repair pass.

```python
_SECTION_NUMBER_TOKEN_RE = re.compile(r"\d+\.\d+(?:\.\d+){0,2}")

def _extract_misplaced_number(text: str) -> tuple[str, int] | None:
    matches = list(_SECTION_NUMBER_TOKEN_RE.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    if match.start() == 0:
        return None
    number = match.group(0)
    remainder = (text[:match.start()] + " " + text[match.end():]).strip()
    remainder = re.sub(r"\s{2,}", " ", remainder)
    if not remainder:
        return None
    return f"{number} {remainder}", number.count(".") + 1
```

Wired into Pass 2 ahead of the existing `_heading_level()` fallback, for
`TITLE`/`SECTION_HEADER` items only.

---

## Fix B — an empty-text heading no longer keeps its raw (possibly level-0) level

**The bug:** v5.5's Pass 2 opens with `if not stripped: continue` before ever
reaching the normalisation step Fix 1 (v5.5) added. An empty-text
`TITLE`/`SECTION_HEADER` — confirmed present on page 19 in the real dump,
right where `"Beginners Circuit"` finally clears — skips normalisation
entirely and keeps whatever level the per-page parser gave it, which can be
level 0. That happens to be *why* the freeze cleared where the review saw it
clear, which is the wrong reason: an empty heading with no text conveys no
section information and shouldn't be able to reset the stack at all, reliably
or not.

**The fix:** heading items with empty text are now handled *before* the
generic empty-string skip: they're rewritten into an empty `TextItem`. The
document serializer emits empty text for an empty item, so
`HierarchicalChunker.chunk()`'s own `if not ser_res.text: continue` drops it
from chunk output entirely — inert, rather than a silent, level-dependent
reset.

---

## Fix C — delete duplicated heading text, don't re-promote it

**The bug:** four cited instances — `"### **7.1 Consistency**"`,
`"### **8.1 Can you make muscles with calisthenics?**"`,
`"### **9.1 Why is nutrition so important?**"`,
`"### **9.2 Nutrition & Calisthenics: 2 Important principles**"` — all glued
onto the *tail* of the preceding paragraph as literal markdown. CommonMark
only recognises an ATX heading (`#`/`##`/`###`) when it's the first thing on
its own line; pymupdf4llm's page markdown apparently emits some heading text
twice (once as a correctly-positioned, blank-line-separated heading that
marko *does* parse, and once more folded into the end of the prior block),
so marko never turns the second copy into a heading node. **Checked against
the real dump for all four cases: the real, correctly-typed heading already
exists elsewhere in the document with matching text.** This is why the fix
deletes the fragment rather than promoting it into a second heading node —
promoting it would create a duplicate entry in the heading path for no
benefit.

**The fix:** `_split_embedded_headings()` first collects the set of texts
already carried by real `SECTION_HEADER`/`TITLE` items, then for every
`PARAGRAPH`/`TEXT` item searches for a trailing `#{1,6}\s*\*{0,2}...\*{0,2}`
fragment; if the recovered text matches something already in that set, the
fragment is stripped from the item's text. A fragment that *doesn't* match
anything already known is left alone — Fix C only removes confirmed
duplicates, never a guess (see `test_unmatched_hash_fragment_is_left_alone`).

Run this pass *after* `_repair_pdf_headings()`, not before — it depends on
real headings already being present and correctly labelled to build its
matching set.

---

## Fix D — promote a chapter heading pymupdf4llm never detected at all

**The bug:** `"10 CRUCIAL TRAINING PRINCIPLES"` has no corresponding heading
item anywhere in the real diagnostic dump — unlike Fix C's cases, there's no
duplicate to delete because there's no original either. It survives only as
`**bold**` text at the start of an ordinary paragraph. Font-size heading
detection is per-page and looks at the single largest font on the page; a
large decorative numeral next to comparatively modest bold chapter text would
explain why this heading in particular was never picked up as `'#'`/`'##'`.

**The fix:** a narrow pattern — 2 to 7 leading ALL-CAPS/number tokens
immediately followed by normal-case prose — is promoted via
`doc.insert_heading(sibling=item, ..., after=False)`. This API was chosen
deliberately over `doc.texts.insert()`: `self_ref` in this version of
docling-core is positional (`#/texts/N`), confirmed by direct inspection, so
a naive list insert would silently invalidate every ref after the insertion
point. `insert_heading()` instead reorders `doc.body.children` (which is what
`HierarchicalChunker`'s traversal actually walks) without touching any
existing item's position in the flat `doc.texts` list — verified directly
against the installed `docling-core` before writing the fix.

**This is a heuristic, not a general-purpose title detector**, and the code
says so. A document whose ordinary prose legitimately opens with a
capitalised multi-word phrase could be mis-promoted by this pattern; it isn't
generalised further than the one confirmed case this patch was built against.
`test_ordinary_prose_is_not_mis_promoted` and
`test_already_existing_heading_is_not_duplicated` cover the two failure modes
that would matter most (false-positive promotion; double-promoting something
that already has a proper heading elsewhere).

---

## File ownership for this patch

| File | Action |
|---|---|
| `parsers/pdf_router.py` | [MODIFY] new regexes; `_as_section_header()` gains `text=`; Pass 2 gains Fix A/B; new `_extract_misplaced_number()`, `_split_embedded_headings()` (Fix C+D), invoked at the end of `_repair_pdf_headings()` |
| `core/chunker.py` | **no change** |
| `docling_parser.py` | **no change** |
| `config.py` | **no change** |
| `tests/parsing_arch/v5_6/test_heading_review_fixes.py` | [NEW] — 16 tests, covering Fixes A–D plus markdown formatting edge cases |

## Validation

All four fixes reproduced and tested offline against the installed
`docling-core` (`HierarchicalChunker` + real `insert_heading()`), using the
exact strings quoted in the review and diagnostic dump — not synthetic
stand-ins. A combined end-to-end replay of the real page-16-through-19
sequence (Greasing 6.4 → Circuit 6.5 → Chest Circuit 6.5.1 → Advanced/
Beginners Circuit → 10 CRUCIAL... → 7.1 Consistency → empty title → 7.5
Bodybuilding mind) produces a clean, correctly-nested heading path with no
freeze and no duplicate/orphan heading, run manually and inspected line by
line before this doc was written up. Existing v5.2/v5.4/v5.5 suites re-run
unchanged and green.

## Non-regression checklist

- [x] `tests/parsing_arch/v5_2/`, `v5_4/`, `v5_5/` pass unchanged (37 passed, 2 xpassed)
- [x] `tests/parsing_arch/v5_6/test_heading_review_fixes.py` passes (16 passed)
- [x] `core/chunker.py` diff is empty
- [x] `docling_parser.py` diff is empty
- [ ] Manual spot-check: rerun `test_parse.py` against the same PDF; confirm
      `"Greasing 6.4 the Groove"` / `"Strength & Skill Routine 5.7"` /
      `"Circuit t Training 6.5"` / `"Chest Circuit 6.5.1"` / `"Hydration 9.6"`
      now read number-first at the correct level; confirm no chunk contains a
      literal `###` or `**N.N ...**` fragment; confirm `"10 CRUCIAL TRAINING
      PRINCIPLES"` appears as its own heading and stays in `chunk.meta.headings`
      through §7.1–7.4
- [ ] Do **not** attempt the CTA/bullet or table-content issues from this
      patch — deferred, see "Not attempted here" above
