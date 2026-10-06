# Handoff & Progress Summary

## Overview
This document summarizes the recent changes made to successfully integrate the `dev` branch's new parsing architecture (`ParserRouter`) into the ingestion pipeline, effectively replacing the legacy parser while fixing database and metadata bugs. 

The pipeline is now successfully tested and working for TXT file parsing.

## Major Changes Made

### 1. Architectural Integration of `ParserRouter`
- **`api/deps.py`**: Swapped out the legacy `Parser` dependency injection for the new `ParserRouter`. 
- **`services/ingestion_service.py`**: Updated the `IngestionService` to expect `ParserRouter`. The service now correctly passes raw file bytes and filename to `ParserRouter.parse()`, which handles dispatching the content to the correct specific parser (like `TextParser` for txt/md).
- **`main.py`**: Removed the deprecated `legacy_router` to force all ingestion traffic through the modern, versioned `/api/v1/documents` endpoint. 

### 2. SQLAlchemy Schema & Migration Fixes
- **`db/models/document.py`**: Discovered and fixed a critical SQLAlchemy crash by adding the missing `versions` relationship back-reference (`Mapped[list["DocumentVersion"]] = relationship(...)`).
- **`db/models/document_version.py`**: Modified the `normalized_hash` type annotation from `str | None` to `str` (with `nullable=True`) to prevent a `TypeError` crash related to Python 3.14's `typing.Union` handling.
- **`db/models/__init__.py`**: Exported `DocumentVersion` so that Alembic's autogenerate feature can correctly detect it.
- **`alembic/versions/`**: Deleted broken and incomplete legacy migrations and successfully generated a new, unified initial migration (`b3801174c558_initial.py`) that properly provisions both the `documents` and `document_versions` tables.

### 3. ChromaDB Metadata Fixes in `Chunker`
- **`core/chunker.py`**: 
  - Fixed a crash where ChromaDB would reject insertions because of invalid metadata types (Chroma only accepts `str`, `int`, `float`, or `bool`). 
  - Modified `_split_docling` to gracefully omit the `page` metadata property entirely instead of passing `None` when a chunk lacks a page number (e.g. for TXT files).
  - Ensured `page_numbers` are converted from lists into comma-separated strings to comply with ChromaDB's strict validation rules.

## Current State
- The ingestion pipeline is fully operational for `.txt` files.
- The pipeline correctly handles file uploading, parsing via `TextParser` (powered by `docling`), chunking, embedding via local HuggingFace models, indexing into ChromaDB, and tracking metadata in SQLite.

## Next Steps
- Implement and test DOCX file parsing integration.
- Implement and test PDF routing/parsing integration.
- Eventually remove any remaining obsolete legacy parsers if no longer needed.
