import os
import sys
import logging
from pathlib import Path

# Enable picture description
os.environ["ENABLE_PICTURE_DESCRIPTION"] = "true"

import config as cfg
from parsers.docling_parser import DoclingParser
from docling_core.types.doc import DocItemLabel, PictureDescriptionData

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format="%(name)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diagnostic")

pptx_path = Path(r"C:\Users\vaibh\Downloads\EL Phase 1(3rd sem).pptx")
print(f"--- STEP 1 VERIFICATION ---")
print(f"File: {pptx_path}")
print(f"Size: {pptx_path.stat().st_size} bytes")

file_bytes = pptx_path.read_bytes()

print(f"\n--- STEP 2: PARSING WITH PICTURE DESCRIPTION ENABLED ---")
parser = DoclingParser()
doc = parser.parse(file_bytes, pptx_path.name)

print(f"\n--- doc.pictures ({len(doc.pictures)} entries) ---")
for idx, pic in enumerate(doc.pictures):
    print(f"\n[Picture #{idx}]")
    print(f"  self_ref: {getattr(pic, 'self_ref', 'N/A')}")
    print(f"  parent:   {getattr(pic, 'parent', 'N/A')}")
    
    # Check prov
    prov = getattr(pic, 'prov', None)
    if prov:
        for p in prov:
            print(f"  prov: page_no={getattr(p, 'page_no', None)}, bbox={getattr(p, 'bbox', None)}")
    else:
        print("  prov: None")

    # Check annotations
    annotations = getattr(pic, 'annotations', []) or getattr(pic, 'meta', [])
    print(f"  annotations count: {len(annotations)}")
    for a_idx, ann in enumerate(annotations):
        print(f"    Annotation #{a_idx}: type={type(ann).__name__}")
        print(f"      text: {getattr(ann, 'text', None)}")
        print(f"      provenance: {getattr(ann, 'provenance', None)}")

print(f"\n--- CAPTION / [Figure description] text items in doc.texts ---")
captions = [t for t in doc.texts if t.label == DocItemLabel.CAPTION or "[Figure description]" in (t.text or "")]
print(f"Total caption/figure items found: {len(captions)}")
for c in captions:
    print(f"  label={c.label}, parent={getattr(c, 'parent', 'N/A')}, text={c.text[:120]}")

print("\n--- DIAGNOSTIC COMPLETE ---")
