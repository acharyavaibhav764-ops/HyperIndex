# v5.9.4 plan: separator-fragment junk chunks

Apply after v5.9.3, from the repo root: `patch -p1 < docs/v5_9_4.patch`.
Input checked: `diag_output2_1.txt` (89470K2.GB0_V2, 82 chunks, produced with v5.9.3).

## 1. Verdict on the v5.9.3 output

Compared line by line with the v5.9.2 output, the only content changes are the intended ones:
chunk 43 no longer has `Yes (2 x Power for room modules =)` (now `2 x Power for room modules =`, last cell `Yes`);
`Yes ()` is gone; the fullwidth parentheses in chunk 80 are ASCII; `Yes` count 55 -> 54 (the legend tick). Nothing else moved
(the remaining diff is console line-wrapping and timestamps). Still 82 chunks, 1 `toc`, no private-use characters.

## 2. Remaining defect

Chunks 41 (p.17) and 62 (p.21) are junk: a breadcrumb heading plus half a table separator row, e.g.
`3 Electrical connection / 3.8 Wiring terminals and their function: / -------------------|--------|-------|`.
The line chunker cut the separator row in the middle, so it lost its leading `|` and the v5.9.1 junk rule (which looks at lines starting with `|`) never matched.
They are retrievable, carry no information, and their heading would outrank the real table chunk for a "terminals" query.

## 3. Change

`core/chunk_cleanup.py`: a chunk made only of breadcrumb-style lines (at most 3, each a short heading, not a sentence, no `|`) plus a separator fragment is dropped.
Chunks with a sentence, a table row or a normal `|---|` separator are untouched.
`tests/parsing_arch/v5_9/test_v5_9_4.py`: 3 tests.

## 4. Verified

32 tests pass (v5.9.1 to v5.9.4, including the real-PDF ones). Run over the 82 real chunks, v5.9.4 removes exactly chunks 41 and 62 and nothing else.
Not run through Docling.

## 5. Not changed

- `recovered_text` chunks 40 and 57 carry a page-number line (`[Recovered text] 16 DBUS B ...`, `[Recovered text] 20`): the coverage check re-adds the footer number.
- 23 `recovered_text` chunks remain overall.
