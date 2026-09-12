# Plan: RAG Pipeline Modularization (Symmetrical 6 Components)

Organize the RAG pipeline into 6 clean, symmetrical modules with **zero backward compatibility overhead** and **zero logic changes**:

1. **`uploader`** ([uploader.py](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/uploader.py)) - MinIO object storage (`ensure_bucket`, `upload_files`, `download_file`).
2. **`parser`** ([parser.py](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/parser.py)) - Multi-format text extraction (PDF, DOCX, DOC, TXT, MD).
3. **`chunker`** ([chunker.py](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/chunker.py)) - Text splitting into chunks with overlap, metadata, and chunk IDs.
4. **`embeddings`** ([embeddings.py](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/embeddings.py)) - Vector embedding generation via `DefaultEmbeddingFunction`.
5. **`retriever`** ([retriever.py](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/retriever.py)) - ChromaDB vector store persistence (`upsert`) and semantic query retrieval (`retrieve`).
6. **`generator`** ([generator.py](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/generator.py)) - Local Ollama model invocation and prompt construction.

---

## Pipeline Flow

```text
[ Raw File Upload ]
        │
        ▼
   uploader.py           (Uploader: MinIO upload & download)
        │ (raw bytes)
        ▼
     parser.py           (Parser: format extraction into pages)
        │ (pages: page_number, text)
        ▼
     chunker.py          (Chunker: RecursiveCharacterTextSplitter)
        │ (chunks, metadatas, chunk_ids)
        ▼
    embeddings.py        (Embeddings: DefaultEmbeddingFunction)
        │ (embeddings)
        ▼
    retriever.py         (Retriever: ChromaDB vector upsert & semantic query)
        ▲
        │ (query question)
   [ User Query ]
        │
        ▼
    retriever.py         (fetch top-k relevant chunks & distances)
        │
        ▼
    generator.py         (Generator: Ollama LLM prompt & grounded generation)
        │
        ▼
   [ Final Answer ]
```

---

## Changes to Existing Files

- **`uploader.py`**: Hosts `Uploader` directly with clean `upload_files` and `download_file` (no backward compatibility aliases).
- **`file_service.py`**: Removed (superseded by `uploader.py`).
- **`rag_service.py`**: Coordinates ingestion: `uploader` $\rightarrow$ `parser` $\rightarrow$ `chunker` $\rightarrow$ `embeddings` $\rightarrow$ `retriever`.
- **`generation_service.py`**: Coordinates querying: `retriever` $\rightarrow$ `generator`.
- **`main.py`**: Clean dependency initialization and wiring to endpoints.

---

## Verification Plan

1. **Compilation**: `python -m py_compile` across all files.
2. **Import & Wireup**: Verify FastAPI app and pipeline initialize cleanly with no missing symbols.
3. **Behavioral Equivalence**: Validate all environment variable defaults, error messages, and payload formats remain identical.
