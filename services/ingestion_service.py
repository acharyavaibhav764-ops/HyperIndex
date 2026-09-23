from fastapi import UploadFile

from core import Chunker, Embeddings, Parser, Retriever, Uploader
from schemas.document import DocumentIngestItem, DocumentIngestResponse


class IngestionService:
    """
    Class to run the entire pipeline from the core modules

    Attributes:
        uploader
        parser 
        chunker
        embeddings
        retriever
    
    Methods:
        ingest_files()
    """

    def __init__(
        self,
        uploader: Uploader,
        parser: Parser,
        chunker: Chunker,
        embeddings: Embeddings,
        retriever: Retriever,
    ):
        self.uploader = uploader
        self.parser = parser
        self.chunker = chunker
        self.embeddings = embeddings
        self.retriever = retriever

    def ingest_files(self, files: list[UploadFile]) -> DocumentIngestResponse:
        """Handles uploading, parsing, chunking, embedding of multiple files and finally return success response"""

        if not files:
            raise ValueError("At least one file is required")

        # Upload files to MinIO
        uploaded_documents = self.uploader.upload_files(files)

        ingested_items = []
        for item in uploaded_documents:
            doc_id = item["document_id"]
            filename = item["filename"]
            size_bytes = item["size_bytes"]

            # Download and parse text pages
            content, _ = self.uploader.download_file(doc_id)
            pages = self.parser.parse(content, filename)

            # Chunk text and attach metadata
            chunks, metadatas, chunk_ids = self.chunker.split(pages, doc_id, filename)

            # Generate vector embeddings
            vectors = self.embeddings.embed(chunks)

            # Persist to ChromaDB
            self.retriever.upsert(
                ids=chunk_ids,
                documents=chunks,
                metadatas=metadatas,
                embeddings=vectors,
            )

            # Append to list of ingested items
            ingested_items.append(
                DocumentIngestItem(
                    document_id=doc_id,
                    filename=filename,
                    size_bytes=size_bytes,
                    collection=self.retriever.collection_name,
                    total_chunks=len(chunks),
                    status="indexed",
                )
            )

        return DocumentIngestResponse(
            message="Documents uploaded and indexed successfully",
            count=len(ingested_items),
            documents=ingested_items,
        )

