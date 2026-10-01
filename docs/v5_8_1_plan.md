# v5.8.1 Implementation Plan

Input: `v5_8_chunks.txt` from `verify_v5_8.py` (118 chunks).

## Result of the v5.8 end-to-end run
Fixed and confirmed in the real dump: no `###` / `**` / `*x*`; no chunk ends with the next chunk's heading; contents table is `1.`..`12.`; `6.5.1 Chest Circuit` and `6.5.2 Core Circuit` are siblings under `6.5 Circuit Training`; captions read `Day 1` / `Day 2` under 9.8; `r ^ Start Now` gone; `THE FULL JOURNEY TIMELINE` fixed. (The 10 remaining "Day 7" strings are the real weekly-table columns.) So the `formatting` clearing, caption renumbering and heading-number pass all took effect.

## One remaining failure: chunk #118 `Calisthenics Family`
Cause (my mistake): that chunk is not produced by HybridChunker. It is the Gap-B synthetic chunk for a heading item on p.36 that no chunk's heading path contains. The v5.8 post-pass runs before Gap B, so it never saw it, and my earlier simulation on the 5.7 dump hid this.

## Fix
- `core/chunk_cleanup.py`: new `is_micro_label()` (one line, < 40 chars, <= 3 words, no digits), reused by the post-pass.
- `core/chunker.py`: the Gap-B loop skips such a heading for `.pdf` files when `CHUNK_POSTPROCESS` is on. Non-PDF heading-only chunks (slides) are untouched.
- One new test.

## Apply
`patch -p1 < docs/v5_8_1.patch`, then `python -m pytest tests/parsing_arch/v5_8 -q` and re-run `verify_v5_8.py` (the "no heading-only / micro chunks" check should now pass).
Dry-run applies cleanly on the v5.8 files. Tests: 11 pass. Not run end to end (no Docling here).
