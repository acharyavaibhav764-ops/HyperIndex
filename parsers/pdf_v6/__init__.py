"""v6 PDF figure pipeline: deterministic figure cards, procedure chunks, optional VLM connections.

Additive package (v5.9's ``parsers/pdf_figures.py`` is left untouched and still serves
``PDF_FIGURE_PIPELINE=v5``).  Modules, in the order the phases add them:

    text.py       P2  string helpers (normalise, caption sanity, heading, classifier-label strip)
    geometry.py   P2  Docling prov bbox -> PyMuPDF points, picture class read-out
    labels.py     P2  exact labels from the PDF text layer, technical-token test
    gate.py       P2  which pictures are skipped and why
    cards.py      P2  per-page orchestration -> Figure cards
    procedure.py  P3  step-by-step illustration pages -> one ordered Procedure chunk
    ocr.py        P4  optional RapidOCR labels for diagrams without a text layer
    vlm.py        P4  local VLM (Ollama) connections, validated against the figure's own labels
    store.py      P5  figure crops in MinIO + typed image_figure chunks
"""
