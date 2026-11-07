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
                          Unified block-level schema
                        { text, page, bbox, source_backend }
                                      │
                       structure-aware chunker (heading-based,
                        merge-small / split-large — not char-count)
                                      │
                              [optional] contextual
                             chunk-header generation
                                      │
                                embeddings → Qdrant
```

### The PDF branch — routed page by page, not document by document

This is the part that actually saves you compute. A 40-page manual is often 36 clean digital pages, 3 pages with a spec table, and 1 scanned diagram — paying a heavy parser's cost for all 40 pages because 4 need it is exactly the "pile of models" you want to avoid. Instead, every page gets cheaply triaged *first*, and only then handed to whichever backend actually fits it.

#### What "triage" means, concretely

Before any real parsing happens, open the PDF with plain PyMuPDF (`fitz`) and pull three signals per page — this takes milliseconds, no models involved:

- **Does the page have a real text layer?** `page.get_text()` — if this comes back empty or near-empty, the page is scanned/image-only.
- **How much of the page is image, not text?** sum the area of embedded image bounding boxes ÷ total page area.
- **Does the page contain a table?** `page.find_tables()` — a lightweight geometric table detector built into PyMuPDF itself, no external model needed.

That's it — three cheap checks, no OCR run yet, no model loaded yet. The routing decision falls out of those three signals:

```python
text_tokens   = len(page.get_text().split())
has_text      = text_tokens > 10
image_ratio   = image_bbox_area(page) / page_area(page)
has_table     = len(page.find_tables().tables) > 0

if not has_text or image_ratio > 0.5:
    route = "OCR_VLM_TIER"     # scanned or image-dominated → needs real OCR/VLM
elif has_table:
    route = "DOCLING"          # has a real table → needs structure-aware extraction
else:
    route = "PYMUPDF4LLM"      # clean digital text → cheapest path is good enough

# independent of the routing above — flag likely cover/front-matter pages
is_front_matter = (page_number <= 2) and (text_tokens < 30) and (image_ratio > 0.6)
```

Treat the exact numbers (`10`, `0.5`, `30`, `0.6`) as starting points, not gospel — §7 already flags that these need to be tuned against a real sample of your Honeywell PDFs, since "how image-heavy is a normal page" will vary by manual type.

| Page looks like… | Send to | Why |
|---|---|---|
| Real text layer, low image coverage, no tables detected | **PyMuPDF4LLM** | Fastest option, and — counterintuitively — often *more* faithful on clean text than the "AI" parsers (see §2) |
| Text layer present but `page.find_tables()` hits, or content looks tabular | **Docling** (TableFormer) | The one tool here purpose-built for structure-preserving table extraction |
| No text layer / low OCR confidence / high image coverage | **OCR + VLM tier** | These pages are scanned or image-only — no shortcut works here |
| Page 1 (or any page) with very little text and mostly image | Tag `front_matter`, store as doc metadata — don't chunk it normally | No tool auto-detects "this is a cover page" — you have to flag it yourself (see §5, Q4) |

#### How the pages get stitched back into one document

Each page gets parsed independently by whichever backend it was routed to, so you end up with mismatched output shapes (PyMuPDF4LLM markdown for some pages, a DoclingDocument for others, raw OCR text for others). Reassembly is just: sort every block by `(page_number, y-position on page)`, and tag each block with which backend produced it (`source_backend`) before merging. That ordering is enough to keep headings, paragraphs, and tables in the right sequence even though different pages were parsed by different tools — the chunker downstream then works over one flat, ordered list of blocks and genuinely doesn't need to know which backend touched which page. This tagging is also exactly what feeds your API's existing page-number/source-metadata response, so nothing changes on that side.

### Master table — all file types

| File type | Route | Why |
|---|---|---|
| PDF, clean digital page | PyMuPDF4LLM | Fast, and benchmark data says it's often *more* faithful than heavier tools on plain text |
| PDF, table-detected page | Docling (TableFormer) | Only tool here purpose-built for table structure recovery |
| PDF, scanned / no text layer | DeepSeek-OCR2 | Leads current OmniDocBench numbers at a fraction of the token cost of older models |
| PDF, diagram/photo needing a description | Same model (DeepSeek-OCR2), different prompt | See §3 — one model can do both jobs |
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

## 4. Chunking

- **Don't** chunk by raw character count. Use the structure the parsers already give you (headings, section hierarchy) to define chunk boundaries — merge small adjacent sections, split oversized ones. This works the same regardless of which backend (PyMuPDF4LLM, Docling, DeepSeek-OCR2) produced a given block, which is the entire point of merging everything into one unified schema before chunking.
- **Optional upgrade — contextual chunk headers:** prepend a short (1–2 sentence) auto-generated blurb to each chunk before embedding — e.g. "This chunk is from the Installation section of the XYZ Controller manual, page 14." Anthropic's own published research on this technique (Contextual Retrieval) measured a real, meaningful drop in retrieval-failure rate from doing this. It costs one small LLM call per chunk at index time (one-time, amortizable). Caveat: this only helps if the model generating the blurbs is actually good at summarizing accurately — your current `llama3.2:3b` is a plausible risk here; if you add this, consider a slightly larger local model just for the indexing-time summarization step (your generation model at query time can stay 3B).

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
| Image-to-text association is positional, not semantic | Multi-column layouts, wrap-around figures, "see figure below" references | Don't assume adjacency in the output means topical relevance — validate on a few real multi-column pages |
| Picture description is a separate opt-in step, not automatic | Any picture the parser is asked to describe | Explicitly enable it and prompt for it (`do_picture_description` in Docling, or a descriptive prompt against DeepSeek-OCR2) |
| DeepSeek-OCR2's captioning quality on real photographs is unbenchmarked | Manuals with genuine photos (not just diagrams) | Spot-check before trusting it; add Qwen2.5-VL only if needed (see §3) |

---

## 7. Before You Build This — What to Test First

1. **Pull ~20 real Honeywell PDFs** and run the triage signals (text-layer presence, image-area ratio, `find_tables()` hits) across every page. Confirm the thresholds actually split "clean" from "needs heavier parsing" the way you'd expect — tune them against your real corpus, not assumptions.
2. **Check whether your corpus actually mixes within documents** (some clean pages + some scanned pages in the same file) or is more bimodal (whole documents are either all-clean or all-scanned). If it's bimodal, document-level routing is simpler to build and nearly as efficient as page-level routing — worth checking before committing to the extra engineering complexity.
3. **Run DeepSeek-OCR2's descriptive prompt against a handful of pages with real photos/diagrams** and judge caption quality yourself before deciding whether you need a second vision model.
4. **If you add contextual chunk headers**, spot-check the generated blurbs for accuracy before trusting them in production — a bad auto-summary is worse than no summary.

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

**Chunking**
- Anthropic, "Contextual Retrieval" (2024) — the technique referenced in §4

---

*This document consolidates research from three parallel AI research sessions (this thread, plus Gemini's independent pass) plus targeted 2026 benchmark verification. Treat the architecture in §1 as the working default — the table in §7 is what should be validated against your actual document corpus before this goes into production.*
