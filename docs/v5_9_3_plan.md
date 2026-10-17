# v5.9.3 plan: leftovers after v5.9.2, checked on the new SEM output

Apply after v5.9.2, from the repo root: `patch -p1 < docs/v5_9_3.patch`.
Input checked: new `diag_output2.txt` (89470K2.GB0_V2, 82 chunks, produced with v5.9.2) against the real `89470K2.GB0_V2.pdf`.

## 1. Verdict on the v5.9.2 output

| Check | Result |
|---|---|
| Ticks in Door (D1-D3), Bathroom/WC (T1-T3), PoC (P1-P5), SCL mode table, range-of-functions table | Correct: every Yes/No matches the PDF (e.g. D3 `Yes / No / Yes / 1 / No`, P4 `Yes / Yes / No / Yes`). `Yes` count went from 3 to 55. |
| Wiring-terminals table (p.17) | Body rows correct (`Power in: Yes Yes No`, `2 x 2 Input: No No Yes`, `ABUS: Yes (Only as a support clamp) / Yes / No`). **Last row wrong**, see 2.1 and 2.2. |
| Private-use glyphs | None left. |
| ToC | One `toc` chunk, pages 2-3. |
| `Γ Ç ┬ ░ ├ ñ ╖` characters | Display artefacts of the PowerShell redirect (the file is UTF-16 of console-decoded text): `Wei├ƒ` is `Weiß`. Not chunk defects. |
| `∩╝ê` / `∩╝ë` in the specifications table | Not glyphs: they are the fullwidth parentheses `（` `）` that the PDF really contains. Harmless, but now mapped to ASCII. |

## 2. What was still wrong, and the fix

1. **Legend tick written into a table row.** On p.17 the legend swatch ("tick = available") lies inside the last body row's box, so the cell became `Yes (2 x Power for room modules =)`. Reproduced on the real page: v5.9.2 gives `Yes (= available)`. Fix: an image with `=` as its next word on the same line is a key, not a value, and is skipped (`_is_legend_swatch`).
2. **`Yes ()`.** The SCL cell holds a footnote marker (`*`); chunk cleanup strips `*`, leaving `Yes ()`. Fix: a cell text without a letter or digit is not kept as qualifier, so the result is `Yes`.
3. **Fullwidth characters** (`（ ） ：`) are mapped to ASCII in page markdown and in the raw text used for the coverage check.

## 3. Verified

29 tests pass: the v5.9.1, v5.9.2 and 4 new v5.9.3 tests, including the real-PDF ones (K2 pp. 5, 17, 21; STIP p. 16). On the real K2 p.17 table (Docling-like grid, exact and shrunk boxes) the patch marks exactly the 16 body ticks (2+3+2+2+1+2+1+3) and leaves the legend as `= available`. Not run through Docling itself.

## 4. Not changed

- 23 `recovered_text` chunks remain, so some page text still comes back through the coverage check instead of the table/figure route (e.g. chunk 43, a table row from p.17). Not touched here.
- The ToC chunk repeats `3 Electrical connection` (a heading echoed in the PDF text layer) and carries the PDF's own `123` typo for page 12.
