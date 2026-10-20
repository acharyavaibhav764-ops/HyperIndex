"""v6 phase 6: which local VLM reads your diagrams best, with and without labels?

Run from the repo root with Ollama up and the models pulled (python scripts/qwen_setup.py start):

  python scripts/figure_eval.py list --pdf manual.pdf --pages 1-12
  python scripts/figure_eval.py run  --pdf manual.pdf --gold scripts/gold_figures.json \\
        --models qwen2.5vl:3b,qwen3-vl:4b --ollama http://localhost:11434 > results.csv

``list`` prints candidate figure boxes (raster images + vector drawing clusters, top-left points)
so you can write the gold file.  ``run`` scores, per figure and model, two prompts:
  grounded = the figure's exact labels are in the prompt (what PDF_VLM_ENABLED=true ships)
  blind    = no labels in the prompt (what the old SmolVLM path effectively did)
Only connections that pass validation count, because only those would reach the index.
Gate for switching the VLM on: kept-connection precision >= 0.9 on the gold set and grounded
clearly above blind.  Precision matters more than recall: a wrong wire is worse than a missing one.
"""
import argparse
import json
import pathlib
import sys
import time
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
if "parsers" not in sys.modules:  # import parsers.pdf_v6 without running parsers/__init__ (needs Docling)
    _pkg = types.ModuleType("parsers")
    _pkg.__path__ = [str(ROOT / "parsers")]
    sys.modules["parsers"] = _pkg

from parsers.pdf_v6 import gate, labels, ocr, text, vlm  # noqa: E402


def _pairs(conns):
    return {frozenset((text.norm(c[0]), text.norm(c[1]))) for c in conns}


def score_edges(kept, gold):
    """kept/gold: iterables of (a, b[, via]).  Undirected, normalised.  -> (precision, recall)."""
    k, g = _pairs(kept), _pairs(gold)
    tp = len(k & g)
    return (tp / len(k) if k else 0.0, tp / len(g) if g else 0.0)


def label_recall(found, gold_labels):
    f = {text.norm(x) for x in found}
    g = [text.norm(x) for x in gold_labels]
    return sum(1 for x in g if x in f) / len(g) if g else 1.0


def _pages(spec, n):
    if not spec:
        return range(n)
    a, _, b = spec.partition("-")
    return range(int(a) - 1, min(int(b or a), n))


def cmd_list(args):
    import pymupdf
    pdf = pymupdf.open(args.pdf)
    for p in _pages(args.pages, len(pdf)):
        page = pdf[p]
        boxes = [("image", tuple(i["bbox"])) for i in page.get_image_info()]
        try:
            boxes += [("vector", tuple(r)) for r in page.cluster_drawings()]
        except Exception:
            pass
        for kind, b in boxes:
            if gate.geometry_skip(b):
                continue
            found = labels.extract_labels(page, b)
            print(f"p{p + 1:>3} {kind:6} bbox=[{b[0]:.0f},{b[1]:.0f},{b[2]:.0f},{b[3]:.0f}] "
                  f"labels={len(found)} technical={labels.is_technical(found)}")


def cmd_run(args):
    import pymupdf
    pdf = pymupdf.open(args.pdf)
    gold = json.loads(pathlib.Path(args.gold).read_text(encoding="utf-8"))
    print("id,model,prompt,label_recall,proposed,kept,precision,recall,seconds")
    for fig in gold:
        page = pdf[int(fig["page"]) - 1]
        bbox = tuple(fig["bbox"])
        found = labels.extract_labels(page, bbox)
        src = "text_layer"
        png = ocr.render_crop(page, bbox, args.dpi)
        if len(found) < labels.MIN_LABELS_FOR_CARD:
            found, src = ocr.ocr_labels(png, px_per_pt=ocr.effective_dpi(bbox, args.dpi) / 72.0), "ocr"
        lr = label_recall(found, fig.get("labels", []))
        gold_edges = [tuple(e) for e in fig.get("edges", [])]
        for model in args.models.split(","):
            for mode in ("grounded", "blind"):
                prompt = vlm.build_prompt(found if mode == "grounded" else [], fig.get("section", ""), "")
                t0 = time.time()
                try:
                    raw = vlm.parse_vlm_json(vlm.chat(png, prompt, model, args.ollama, "", args.timeout, "2m"))
                except Exception as exc:
                    print(f'{fig["id"]},{model},{mode},{lr:.2f},ERR,"{exc!r}",,,')
                    continue
                kept = vlm.validate_connections(raw, found)
                p, r = score_edges([(c["from"], c["to"]) for c in kept], gold_edges)
                print(f'{fig["id"]},{model},{mode},{lr:.2f},{len(raw)},{len(kept)},{p:.2f},{r:.2f},'
                      f"{time.time() - t0:.1f}")
        print(f"# {fig['id']}: labels from {src}: {len(found)}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list")
    a.add_argument("--pdf", required=True)
    a.add_argument("--pages", default="")
    b = sub.add_parser("run")
    b.add_argument("--pdf", required=True)
    b.add_argument("--gold", required=True)
    b.add_argument("--models", default="qwen2.5vl:3b")
    b.add_argument("--ollama", default="http://localhost:11434")
    b.add_argument("--dpi", type=int, default=200)
    b.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args(argv)
    {"list": cmd_list, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
