"""
Quick CLI utility to test parsing and hybrid chunking on any text or Markdown file.

Usage:
    python test_parse.py path/to/document.txt
    python test_parse.py path/to/document.md
"""
import sys
from pathlib import Path

from parsers import ParserRouter
from core import Chunker


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage: python test_parse.py <path-to-file>")
        print("Supported: .txt  .md  .docx  .pptx  .doc  .ppt")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File '{file_path}' does not exist.")
        sys.exit(1)

    filename = file_path.name
    file_bytes = file_path.read_bytes()

    print(f"\n[1/3] Reading file: {filename} ({len(file_bytes)} bytes)")
    router = ParserRouter()

    print("[2/3] Routing & parsing to DoclingDocument...")
    try:
        doc = router.parse(file_bytes, filename)
        print("      Parsed into DoclingDocument successfully.")
    except Exception as e:
        print(f"      Parsing failed: {e}")
        sys.exit(1)

    print("[3/3] Chunking via HybridChunker...")
    chunker = Chunker()
    file_id = file_path.stem

    try:
        chunks, metadatas, chunk_ids = chunker.split(
            doc, file_id=file_id, filename=filename
        )
    except Exception as e:
        print(f"      Chunking failed: {e}")
        sys.exit(1)

    total = len(chunks)
    print(f"\n[Result] Successfully produced {total} chunk(s):\n")
    for i, (chunk, meta, cid) in enumerate(zip(chunks, metadatas, chunk_ids)):
        print(f"{'='*70}")
        print(f"Chunk #{i + 1}/{total} | ID: {cid} | Length: {len(chunk)} chars")
        print(f"Metadata: {meta}")
        print(f"{'-'*70}")
        preview = chunk if len(chunk) <= 800 else chunk[:800] + f"\n... [truncated — full length: {len(chunk)} chars]"
        print(preview)
        print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
