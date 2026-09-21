# RAG Document Parsing Architecture — Final Recommendation

**For:** Honeywell Virtual Assistant RAG pipeline
**Covers:** PDF / DOCX / PPTX / legacy DOC-PPT / image ingestion, OCR + vision model choice, chunking
**Status:** Recommendation based on 2026 benchmark data + known tool issues. Validate the triage thresholds against your own corpus before shipping (see §7).

---

## TL;DR

Don't send every document through one heavy "does everything" parser, and don't hand-roll a different library per file type either. Route **per page** through the cheapest tool that's good enough for that specific page, and only escalate to a heavier model when a page actually needs it. Use **one** vision model (DeepSeek-OCR2) for both reading text-in-images and describing diagrams/photos — add a second, dedicated captioning model only if testing shows the first one's photo descriptions are too thin.

---

## 1. The Architecture (start here)

```
                                    FILE
                                      │
                          extension / MIME detect
        ┌──────────┬──────────┬──────┴──────┬─────────────┬──────────────┐
        ▼          ▼          ▼             ▼             ▼              ▼
      TXT/MD      PDF       DOCX          PPTX        legacy DOC/PPT   standalone
        │           │          │             │             │            image
     pass-      per-page    Docling       Docling      LibreOffice        │
     through    triage    (unified doc) (unified doc)  headless →     OCR + VLM
        │       (below)       │             │         re-enter Docling   tier
        │           │         │             │             │              │
        └───────────┴─────────┴─────────────┴─────────────┴──────────────┘
                                      │
                     Unified schema: DoclingDocument
        (Docling-native for table pages; built via convert_string()
          + builder API for PyMuPDF4LLM/OCR pages — see §4)
                                      │
                      Docling's HybridChunker (§4) — tokenizer-aware,
                     heading-hierarchy-driven, structural table handling
                                      │
                              [optional] contextual
                             chunk-header generation
                                      │
                                embeddings → Chroma
```

### The PDF branch — routed page by page, not document by document

This is the part that actually saves you compute. A 40-page manual is often 36 clean digital pages, 3 pages with a spec table, and 1 scanned diagram — paying a heavy parser's cost for all 40 pages because 4 need it is exactly the "pile of models" you want to avoid. Instead, every page gets cheaply triaged *first*, and only then handed to whichever backend actually fits it.

#### What "triage" means, concretely

Before any real parsing happens, open the PDF with plain PyMuPDF (`fitz`) and pull three signals per page — this takes milliseconds, no models involved:

- **Does the page have a real text layer?** `page.get_text()` — if this comes back empty or near-empty, the page is scanned/image-only.
- **How much of the page is image, not text?** sum the area of embedded image bounding boxes ÷ total page area.
- **Does the page contain a table?** `page.find_tables()` — a lightweight geometric table detector built into PyMuPDF itself, no external model needed.

That's it — three cheap checks, no OCR run yet, no model loaded yet.

**Important correction from an earlier draft of this logic:** "image-heavy" and "needs OCR" are *not* the same thing, and treating them as one `if` branch was a real bug. A completely normal engineering page can have a large diagram covering 60–70% of the page while still having perfectly good selectable text underneath and around it. If you route on `image_ratio > 0.5` alone, that page gets sent through full-page OCR — throwing away the exact, already-correct embedded text layer and re-transcribing it through a lossier path for no reason. The two questions have to be asked and answered separately:

- **Does the page need OCR at all?** — governed *only* by whether a real text layer exists. If it does, use it — regardless of how much of the page is also covered by images.
- **Does the page contain a figure worth describing?** — a separate, independent check on individual embedded image regions, not on the page as a whole. A page can get normal text extraction *and* have one specific diagram cropped out and sent for a VLM description, at the same time.

```python
text_tokens = len(page.get_text().split())
has_text    = text_tokens > 10

# table signal: don't treat find_tables() as ground truth on its own — it has real
# false negatives (tables split oddly, or laid out in ways it doesn't recognize).
# OR it with a cheap secondary check rather than trusting one signal blindly.
has_table = (
    len(page.find_tables().tables) > 0
    or looks_tabular(page.get_text())   # e.g. many short lines with consistent
)                                        # whitespace/column alignment

if not has_text:
    route = "OCR_VLM_TIER"        # genuinely scanned page → full-page OCR
elif has_table:
    route = "DOCLING"             # real, extractable text + a table → structure-aware path
else:
    route = "PYMUPDF4LLM"         # real, extractable text, no table → cheapest path

# independent of the route above — check each embedded image on its own, not the
# whole page. Only crop-and-describe images big enough to plausibly be a real figure.
for image in page.get_images():
    if bbox_area(image) / page_area(page) > 0.15:
        queue_for_vlm_description(image)   # one cropped-image call, not a full-page one

# independent of everything above — flag likely cover/front-matter pages
is_front_matter = (page_number <= 2) and (text_tokens < 30) and (image_ratio(page) > 0.6)
```

Treat the exact numbers (`10`, `0.15`, `30`, `0.6`) as starting points, not gospel — §7 already flags that these need to be tuned against a real sample of your Honeywell PDFs, since "how image-heavy is a normal page" will vary by manual type. The `looks_tabular()` check doesn't need to be fancy — a regex over line structure is enough to catch a real chunk of `find_tables()`'s misses without building a full ML table detector.

| Page looks like… | Send to | Why |
|---|---|---|
| Real text layer, low image coverage, no tables detected | **PyMuPDF4LLM** | Fastest option, and — counterintuitively — often *more* faithful on clean text than the "AI" parsers (see §2) |
| Text layer present but `page.find_tables()` hits, or content looks tabular | **Docling** (TableFormer) | The one tool here purpose-built for structure-preserving table extraction |
| No text layer / low OCR confidence / high image coverage | **OCR + VLM tier** | These pages are scanned or image-only — no shortcut works here |
| Page 1 (or any page) with very little text and mostly image | Tag `front_matter`, store as doc metadata — don't chunk it normally | No tool auto-detects "this is a cover page" — you have to flag it yourself (see §5, Q4) |

#### How the pages get stitched back into one document

Each page gets parsed independently by whichever backend it was routed to, so you end up with mismatched output shapes (PyMuPDF4LLM markdown for some pages, a DoclingDocument for others, raw OCR text for others). §4 covers the actual mechanism now: rather than merging into a bespoke intermediate format, each non-Docling page's markdown gets converted through Docling's own markdown backend and folded, page by page, into one running `DoclingDocument`, with page-number provenance attached explicitly as you go. That gets you one real `DoclingDocument` for the whole file, in the right order, ready for `HybridChunker` — and it's also exactly what feeds your API's existing page-number/source-metadata response, so nothing changes on that side.

#### Closing the "positional ≠ semantic" gap, cheaply

§5/Q3 already flags a real limitation: image placement is based on where a figure physically sits on the page, not on which paragraph actually talks about it. A paragraph that says "see Table 4-2 below" and the table itself can end up several blocks apart in reading order, especially across a page break. Solving this *properly* would mean building a real relation-extraction model — not worth it for v1. But most of the value is recoverable with a single, cheap, deterministic pass after everything is merged: regex over the merged text for reference patterns (`Figure\s+\d+`, `Table\s+\d+`, `Fig\.\s*\d+`), matched against caption blocks that start with the corresponding label (`"Figure 3:"`, `"Table 4-2:"`). No model call, no extra latency worth mentioning, and it turns "the figure happens to be nearby" into an explicit link the retriever can actually use.

Most of the fields you'd want per block map directly onto `DoclingDocument`'s own item structure once you've adopted the §4 approach — `type` is the item's label (heading/paragraph/table/picture), `page`/`bbox` come from its `ProvenanceItem`, `parent_section` and `reading_order` fall out of the tree position for free. The one field that genuinely isn't a native `DoclingDocument` field is `references` (the regex-linked figure/table mentions) — I didn't find confirmation that individual items support arbitrary custom metadata beyond the document-level `BaseMeta`, so don't fight the schema to force it in. Keep it as a small, separate side-table (`asset_id → [referencing chunk ids]`) computed after chunking and joined in at retrieval time — same practical effect, without assuming an API guarantee that isn't actually confirmed:

```json
{
  "type": "paragraph | heading | table | figure | caption | list",
  "text": "...",
  "page": 14,
  "bbox": [x1, y1, x2, y2],
  "source_backend": "pymupdf4llm | docling | deepseek_ocr2",
  "parent_section": "Installation > Wiring",
  "reading_order": 17,
  "asset_id": "fig_3_page14.png",
  "references": ["fig_3_page14.png"]
}
```

`type`, `parent_section`, and `reading_order` fall out of the heading hierarchy and page/y-sort you're already computing for chunking — making them explicit fields rather than implicit ordering costs nothing extra. `references` is the one genuinely new piece of work, and it's the regex pass described above, not a model.

**What I'm deliberately *not* building into v1:** a fully generalized semantic document graph with per-block confidence scores across multiple independent dimensions (text/table/image/OCR/layout confidence, each separately weighted). That's a reasonable idea in principle, but it's exactly the kind of complexity this architecture is trying to avoid adding *before* there's evidence it's needed. The regex-based reference link above gets most of the practical benefit for near-zero cost; if the evaluation harness in §7 shows retrieval is still failing specifically because of positional/semantic mismatches after that, build the heavier version then — not speculatively now.

### Master table — all file types

| File type | Route | Why |
|---|---|---|
| PDF, clean digital page | PyMuPDF4LLM | Fast, and benchmark data says it's often *more* faithful than heavier tools on plain text |
| PDF, table-detected page | Docling (TableFormer) | Only tool here purpose-built for table structure recovery |
| PDF, scanned / no text layer | DeepSeek-OCR2 (full page) | Leads current OmniDocBench numbers at a fraction of the token cost of older models |
| PDF, individual large diagram/photo *(independent of whether the rest of the page has text)* | Same model (DeepSeek-OCR2), cropped image + descriptive prompt | Decoupled from full-page routing — a page with good text and a big diagram gets both text extraction *and* a targeted image description, not one or the other |
| DOCX | Docling | Same unified schema as the PDF branch; keeps tables structured |
| PPTX *(currently unsupported in your stack)* | Docling | Zero new dependency — you're already adding Docling for DOCX |
| Legacy `.doc` / `.ppt` | LibreOffice headless → convert → re-enter Docling as DOCX/PPTX | Retires `antiword`; gets legacy files onto the same schema as everything else |
| TXT / MD | Pass-through | Already trivial, no change needed |
| Cover pages / low-text image pages | Heuristic tag → document metadata, not a normal chunk | Nothing auto-detects this |

---

## 2. Why It's Built This Way

### "AI parsers" aren't automatically better — on clean PDFs they can be worse

A 2026 multi-metric benchmark across ~1,000 page-level evaluations found that pymupdf4llm and Docling actually scored **below** plain rule-based extractors (PyMuPDF, pypdfium2) on text-fidelity metrics, while running **100–1,600× slower**. The researchers called this an "extraction paradox": tools built for LLM consumption underperformed simple extractors on the exact thing they're supposed to be good at, on ordinary digital PDFs. That's the concrete justification for *not* defaulting every page to a heavy parser — layout-aware tools earn their cost on complex/scanned material, not on a plain spec sheet.

### But on scanned/complex pages, the gap the other direction is real

Restricted to non-digital (scanned) PDFs, Docling scored **64.0** on olmOCR-Bench against **83.5** for Marker 2 and **83.3** for MinerU. On the current OmniDocBench leaderboard, dedicated OCR/document models (DeepSeek-OCR2, MinerU2.5, PaddleOCR-VL, GLM-OCR) all score in the low-to-mid 90s, while Docling isn't built to compete there at all — it's optimized for producing a clean structured schema on digital documents, not for reading degraded scans. So: never send a scanned page to Docling expecting OCR-grade results. That's what the dedicated OCR/VLM tier is for.

### Known real-world rough edges (worth planning around)

- Docling has an open bug where ~170MB of GPU memory stays allocated even after the converter instance is deleted — matters if it's running inside a long-lived API worker rather than a fresh process per request.
- At least one team benchmarking Docling in production found **no measurable speed difference** between GPU-enabled and CPU-only runs. Don't assume a GPU purchase automatically buys you speed here — verify on your own hardware before committing budget.
- `page_range`, the only page-skipping mechanism Docling has, has had real off-by-one bugs at range boundaries in recent releases. If you build cover-page skipping on top of it, test it against your actual files.

---

## 3. The OCR + Vision Model Decision: One Model, Not Two

**Question this answers:** do you need a separate OCR model and a separate image-captioning model, or can one model do both?

**Short answer: one model is enough to start.** Use **DeepSeek-OCR2** for the entire OCR + image-description tier.

**Why it can do both jobs:**
- Its whole design point ("optical context compression") makes it very cheap per page — it reads document text using far fewer vision tokens than older models at comparable or better accuracy, so it doesn't need a beefy GPU to be fast.
- It wasn't trained purely on document text. Its training mix included a meaningful slice of general vision data (image captioning, object detection) alongside the document-OCR corpus, and its underlying encoder is architecturally general-purpose rather than hard-wired to text recognition. In practice: same loaded weights, two different prompts — a transcription/markdown prompt for reading text, a descriptive prompt for captioning a diagram or photo. No second model to load or swap.

**Why a general vision model (Qwen2.5-VL / Qwen3-VL) alone is the weaker choice here**, even though it's also capable of both jobs: multiple independent 2026 benchmarks show general-purpose VLMs consistently score noticeably below specialized document-parsing models on actual parsing accuracy — one multilingual parsing benchmark put general VLMs around 83–84 versus 92+ for the top specialized model, calling out that they "lag behind top-tier specialized models, particularly in structural parsing" (i.e., tables). Since your manuals will lean on tables and spec sheets, that gap matters more for you than the convenience of a bigger, more "generally smart" model.

**The one honest gap:** DeepSeek-OCR2's document-parsing accuracy is heavily benchmarked and proven. Its *open-domain photo captioning* quality (e.g., "describe this photograph of a valve assembly") is not — every benchmark found for it measures parsing accuracy, not captioning quality the way general VLMs get scored on captioning tasks.

**What to actually do:**
1. Run DeepSeek-OCR2 alone as the single model for the OCR + VLM tier.
2. Test its descriptive-prompt output against a handful of real Honeywell pages that contain genuine photos or diagrams (not just scanned text).
3. If captions come back specific and useful → done, one model covers everything.
4. If captions come back generic/thin specifically on photographic content → add **Qwen2.5-VL (7B)** as a targeted second model, called *only* for pages your triage step already flagged as picture-heavy. Don't add it pre-emptively — add it only once you have evidence the first model actually needs help.

---

## 4. Chunking — Target DoclingDocument Itself, Use HybridChunker

Earlier drafts of this document proposed a bespoke `{type, text, page, bbox, source_backend, references}` JSON schema plus a hand-rolled heading-based chunker. Don't build that — Docling's own document format and chunker do this job already, and they're usable even for pages that never touched Docling's PDF pipeline.

### Why this works even for non-Docling pages

`DoclingDocument` is a public, buildable format — a tree of typed items (headings, paragraphs, tables, pictures) with optional page/bbox provenance on each. Docling exposes two ways to produce one without running its full PDF pipeline:

- **`DocumentConverter().convert_string(markdown_text, format=InputFormat.MD)`** — Docling ships a real markdown backend. Feed it markdown with proper `#`/`##` headings and pipe-table syntax (exactly what PyMuPDF4LLM already emits) and you get back a genuine `DoclingDocument` with real `SectionHeaderItem`/`TableItem` structure, not flattened text.
- **The builder API** — `add_heading()`, `add_text()`, `add_table()`, `add_picture()`, each accepting a `parent` (for hierarchy) and `prov=ProvenanceItem(page_no=..., bbox=...)`. This is the same API Docling's own backends use internally to construct a document — public, not a workaround.

Critically, `HybridChunker` doesn't need bounding-box precision to do its job. It walks the tree using **heading hierarchy + item type** — one chunk per item, tables kept structurally intact, tokenizer-aware splitting of oversized chunks, and merging of undersized neighbors that share the same heading path. Precise bbox is metadata it carries, not something its chunking logic depends on. So a page that only ever produced markdown (PyMuPDF4LLM, or DeepSeek-OCR2 prompted for markdown output) still gets full chunking quality once it's expressed as a `DoclingDocument` — you're not trading chunk quality for triage efficiency.

### The concrete method — keeps the page-level triage from §1 exactly as-is

1. **Docling-routed pages** (table pages) already produce a real `DoclingDocument` fragment natively, bbox included. No conversion needed.
2. **PyMuPDF4LLM / DeepSeek-OCR2 pages** — take that page's markdown output and run it through `convert_string(page_markdown, format=InputFormat.MD)`, **one page at a time**. Doing it per-page (not once for the whole file) is what lets you attribute page numbers correctly — plain markdown has no native concept of "page," so you supply that yourself: walk the returned fragment's items and re-emit them into one running master `DoclingDocument` via the builder API, attaching `prov=ProvenanceItem(page_no=N, bbox=<full-page sentinel>)` as you go — see the note below on why bbox can't just be omitted.
3. Once every page's items are folded into the one master document (in page order), run `HybridChunker` on it **once**, for the whole file.

**The one real trade-off, and it's more specific than "just no bbox":** `ProvenanceItem` requires `page_no`, `bbox`, and `charspan` together in Docling's schema — you can't attach page-number provenance to an item without also supplying *some* bbox value. So on pages that never went through Docling's real layout model, use a clearly-safe sentinel bbox — the full page rectangle (`l=0, t=0, r=page_width, b=page_height`), not a zero-size box — alongside the real page number. This doesn't touch chunk quality: `HybridChunker`'s chunking logic doesn't consume bbox to make decisions. It matters for anything *else* that later touches that bbox assuming it's real geometry — Docling's own picture-description enrichment step, for example, does direct arithmetic on `prov.bbox` (`width = bbox.r - bbox.l`, etc.) with no check that it's meaningful, so a placeholder there would silently crop the wrong region rather than error. Guard against this with the `source_backend` tag already in this architecture: anything that wants to trust bbox precision checks `source_backend == "docling_native"` first and treats bbox as a placeholder otherwise on everything else.

### What you get for free out of this

- `chunker.contextualize(chunk)` renders each chunk as its heading path + text (e.g. `"Installation > Wiring\n<chunk text>"`) before embedding — a deterministic, zero-cost version of the "contextual chunk header" idea below. Prefer this over an LLM-generated blurb unless you have a specific reason the heading path isn't descriptive enough on its own.
- Table chunks stay structurally serialized (row/column form, with headers repeated across a table that spans multiple chunks) instead of being flattened to text — the reference-linking regex pass from §1 also has cleaner text to work against as a result.

### Optional upgrade — LLM-generated contextual chunk headers

If `contextualize()`'s heading path isn't descriptive enough on its own, you can still layer Anthropic's Contextual Retrieval technique on top: prepend a short (1–2 sentence) auto-generated blurb to each chunk before embedding — e.g. "This chunk is from the Installation section of the XYZ Controller manual, page 14." Anthropic's own published research measured a real, meaningful drop in retrieval-failure rate from doing this. It costs one small LLM call per chunk at index time. Caveat: this only helps if the model generating the blurbs is actually good at summarizing accurately — your current `llama3.2:3b` is a plausible risk here; if you add this, consider a slightly larger local model just for the indexing-time summarization step (your generation model at query time can stay 3B). Given `contextualize()` already gives you heading-path context for free, treat this as a second-order upgrade to test, not a default.

---

## 5. Quick Reference — Your Original Questions, Answered

| # | Question | Short answer |
|---|---|---|
| 1 | Does everything output markdown? | PyMuPDF4LLM, Docling, MinerU, MarkItDown: yes, natively. Unstructured: no — it gives you structured JSON elements and you assemble markdown yourself. |
| 2 | Does it run OCR on the same PDF twice? | No. Docling runs one pass per page with several specialized models (layout, OCR, table structure) each handling their own region. The only genuinely "extra" pass is optional picture-*description* (captioning), which is off by default and only touches picture crops, not the whole page again. |
| 3 | How does it associate an image with the right text? | Pure geometry — page number + bounding box + a rule-based reading-order algorithm (not ML). It's positional adjacency, not semantic understanding — a figure referenced two paragraphs later ("see diagram below") still sits wherever it physically sits on the page. |
| 4 | Will it know to skip a cover page? | No. No tool here auto-detects "this is decorative front matter." There's an open, unresolved feature request for exactly this. You have to flag it yourself with a simple heuristic (e.g., page 1, very low text count, high image coverage). |
| 5 | What does the OCR model actually output for an image — a description? | Depends on the step. **OCR** transcribes text that's rendered as pixels — it doesn't know or care what a picture "is." **Picture description** is a separate, opt-in VLM step that produces an actual caption of the image content. They're two distinct capabilities; treat OCR'd text as normal text and VLM captions as a tagged, distinct block (e.g. `[Figure: ...]`) downstream. |

---

## 6. Known Rough Edges — Exceptions & Gotchas

| Issue | Where it bites | What to do |
|---|---|---|
| Docling GPU memory not fully released between conversions | Long-lived API worker processes | Recycle worker processes periodically, or run Docling conversions in short-lived subprocesses |
| GPU vs CPU showed no real speed difference for one team's OCR workload | Hardware budgeting | Benchmark on your own box before buying/allocating GPU for this specifically |
| `page_range` has had off-by-one bugs near range boundaries | Any page-skipping logic (e.g. cover page suppression) | Test against real files, don't trust silently |
| No automatic cover-page / boilerplate detection | Every parser in this stack | Build a simple heuristic (low text + high image ratio) at your application layer |
| `find_tables()` has real false negatives (missed, split, or unconventionally-laid-out tables) | Any page where the table-detection signal is trusted alone | Don't treat it as ground truth — OR it with a cheap secondary text-layout check (see §1); escalate to a real table detector only if the eval harness in §7 shows it's still missing tables |
| `ProvenanceItem` requires `bbox` alongside `page_no` — can't attach one without the other | Building `DoclingDocument` items for pages that never went through Docling's layout model (§4) | Use a full-page sentinel bbox, not a zero-size one, and gate anything that trusts bbox precision on `source_backend == "docling_native"` |
| Image-to-text association is positional, not semantic | Multi-column layouts, wrap-around figures, "see figure below" references | Don't assume adjacency in the output means topical relevance — validate on a few real multi-column pages |
| Picture description is a separate opt-in step, not automatic | Any picture the parser is asked to describe | Explicitly enable it and prompt for it (`do_picture_description` in Docling, or a descriptive prompt against DeepSeek-OCR2) |
| DeepSeek-OCR2's captioning quality on real photographs is unbenchmarked | Manuals with genuine photos (not just diagrams) | Spot-check before trusting it; add Qwen2.5-VL only if needed (see §3) |

---

## 7. Before You Build This — Build an Evaluation Harness, Not Just a Vibe Check

Don't just eyeball whether the routing thresholds "look reasonable" on a few files. The goal was never "did PyMuPDF extract the page correctly" — it's "can the final RAG system actually answer a question correctly using that page." Those are different questions, and only the second one matters. Build something that measures it:

1. **Hand-label a small gold corpus.** Pull ~20–50 representative Honeywell documents and label each page into one category: `CLEAN_TEXT`, `TABLE`, `SCANNED_TEXT`, `DIAGRAM`, `PHOTO`, `MIXED`, `COVER`. This takes an afternoon and is the single highest-leverage thing you can do before writing production routing code, because every threshold in §1 is a guess until it's checked against real labels.
2. **Measure routing accuracy against those labels** — did `CLEAN_TEXT` pages actually get routed to PyMuPDF4LLM, did `TABLE` pages hit Docling, did `SCANNED_TEXT`/`DIAGRAM`/`PHOTO` pages hit the OCR/VLM tier, did `COVER` pages get flagged as front matter? This is where you'll actually discover whether the `0.15`/`0.5`/`30` thresholds from §1 need adjusting for your specific manuals.
3. **Measure per-capability accuracy, not just routing:** OCR accuracy on the `SCANNED_TEXT` pages, table-structure accuracy on the `TABLE` pages, and — separately — whether the figure descriptions on `DIAGRAM`/`PHOTO` pages are actually *useful* (this is where you decide the DeepSeek-OCR2-alone question from §3, with evidence instead of a guess).
4. **Check whether your corpus mixes within documents** (clean pages and scanned pages in the same file) or is more bimodal (whole documents are either all-clean or all-scanned). If it's bimodal, document-level routing is simpler to build and nearly as efficient as page-level routing — worth knowing before committing to the extra engineering complexity page-level routing adds.
5. **The metric that actually matters: write ~30 real questions** a Honeywell technician would plausibly ask, run them through the whole pipeline end to end, and check whether the answers come back correct and properly sourced. A page can parse "beautifully" by every metric above and still fail to produce a right answer, and the reverse also happens — this is the check that actually tells you whether the architecture works, not just whether the parsing looks plausible.
6. **If you add contextual chunk headers**, spot-check the generated blurbs for accuracy before trusting them in production — a bad auto-summary is worse than no summary.

Keep this harness around after launch, not just as a one-time pre-launch gate — it's also exactly what tells you, later, whether it's time to escalate any of the "deferred until evidence shows it's needed" decisions in this document (the table-confidence check, the reference-linker, a second vision model, a richer relation schema).

---

## Sources & Further Reading

**Benchmarks**
- OmniDocBench (OpenDataLab) — the primary public document-parsing benchmark referenced throughout: https://github.com/opendatalab/OmniDocBench
- Docling Technical Report (arXiv 2408.09869) — architecture details, reading order, OCR pipeline
- DeepSeek-OCR / DeepSeek-OCR2 papers (arXiv 2510.18234, arXiv 2601.20552) — token compression, training data composition

**Known issues (GitHub)**
- Docling GPU memory retention: docling-project/docling issue #2954
- Docling GPU/CPU parity report: docling-project/docling issue #2727
- Cover-page / page-exclusion feature request (unresolved): docling-project/docling issue #2086
- `page_range` boundary bugs: docling-project/docling issues #2655, #1469

**Docling documentation**
- Picture description / enrichment options: https://docling-project.github.io/docling/usage/enrichments/
- DoclingDocument schema & reading order: https://docling-project.github.io/docling/concepts/docling_document/
- DoclingDocument construction API (`add_heading`, `add_text`, `add_table`, etc.): https://docling-project.github.io/docling/reference/docling_document/
- Markdown backend / `convert_string`: https://docling-project.github.io/docling/examples/run_md/, https://docling-project.github.io/docling/reference/document_converter/
- HybridChunker internals: https://docling-project.github.io/docling/concepts/chunking/

**Chunking**
- Anthropic, "Contextual Retrieval" (2024) — the technique referenced in §4

---

*This document consolidates research from three parallel AI research sessions (this thread, plus Gemini's and ChatGPT's independent passes) plus targeted 2026 benchmark verification. ChatGPT's review specifically caught a real bug in the original triage logic (image-heavy pages were incorrectly treated as needing full-page OCR) — that's now fixed in §1. Its suggestions for a fully generalized, multi-dimensional confidence-scored router and a heavy semantic-relations graph were deliberately not adopted for v1 — see the callout in §1 — in favor of the cheaper fixes that get most of the same benefit. Treat the architecture in §1 as the working default — §7 is what should be validated against your actual document corpus before this goes into production.*
