import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from parsers.docling_parser import DoclingParser
from core.chunker import Chunker
from docling.chunking import HybridChunker

pptx_path = Path(r"C:\Users\vaibh\Downloads\EL Phase 1(3rd sem).pptx")
file_bytes = pptx_path.read_bytes()

# 1. Parse document (plain conversion is sufficient for text/headings)
parser = DoclingParser()
doc = parser.parse(file_bytes, pptx_path.name)

# 2. Inspect slide 13 items in doc
print("=== ITEMS IN DOC FOR SLIDE 13 (page_no=13) ===")
for item, level in doc.iterate_items():
    prov = getattr(item, "prov", None)
    page_no = prov[0].page_no if prov else None
    if page_no == 13:
        label = getattr(item, "label", None)
        text = getattr(item, "text", None)
        print(f"Item: type={type(item).__name__}, label={label}, level={level}, text={text!r}")

# 3. Chunk document using Chunker
chunker = Chunker()
chunks, metadatas, ids = chunker.split(doc, "EL Phase 1(3rd sem)", pptx_path.name)

print("\n=== CHUNKS FOR PAGE 13 ===")
for c, m, cid in zip(chunks, metadatas, ids):
    if m.get("page") == 13 or "Proposed Outcomes" in c or "Low-latency RAG system" in c:
        print(f"Chunk ID: {cid}")
        print(f"Metadata: {m}")
        print("FULL UNTRUNCATED TEXT:")
        print(c)
        print("=" * 60)

# 4. Also inspect raw HybridChunker DocChunk.meta.headings
print("\n=== RAW HYBRIDCHUNKER DOCCHUNKS FOR SLIDE 13 ===")
h = HybridChunker()
for raw_c in h.chunk(doc):
    page_no = None
    try:
        prov = raw_c.meta.doc_items[0].prov
        if prov:
            page_no = prov[0].page_no
    except Exception:
        pass
    if page_no == 13 or "Proposed Outcomes" in raw_c.text or "Low-latency RAG system" in raw_c.text:
        print(f"Raw DocChunk text preview: {raw_c.text[:80]!r}")
        print(f"Raw DocChunk meta.headings: {raw_c.meta.headings}")
        print(f"Contextualized text: {h.contextualize(raw_c)[:120]!r}")

# 5. Check slide 13 XML in zip
z = zipfile.ZipFile(pptx_path)
s13_xml = z.read("ppt/slides/slide13.xml").decode("utf-8")
root = ET.fromstring(s13_xml)
print("\n=== SLIDE 13 XML SHAPES ===")
for sp in root.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}sp"):
    cNvPr = sp.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr")
    ph = sp.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}ph")
    text = "".join(sp.itertext())
    name = cNvPr.attrib.get("name") if cNvPr is not None else None
    ph_attr = ph.attrib if ph is not None else None
    print(f"Shape name={name!r}, ph={ph_attr}, text={text.strip()!r}")
