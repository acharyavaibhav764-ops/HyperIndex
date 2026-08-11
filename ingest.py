import os
import sys
from pathlib import Path
import pickle

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# Global config
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR
sys.path.insert(0, str(PROJECT_ROOT))

KB_DIR = PROJECT_ROOT / "knowledge_base"
INDEX_NAME = "index" # Creates KB_DIR/index.faiss + index.pkl
METADATA_PATH = KB_DIR / "metadata.pkl" # Separate metadata.pkl for easy inspection/debugging outside LangChain

PDF_FILE = PROJECT_ROOT / "data" / "manual.pdf"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

def load_pdf(pdf_path: str):

    # Missing PDF file
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Could not find PDF at '{pdf_path}'")

    # Return pages as list of LangChain Document objects
    print(f"[LOGGING] Loading PDF: {pdf_path}")
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()
    print(f"[LOGGING] Loaded {len(pages)} page(s)")
    return pages


def chunk_documents(pages, chunk_size: int, chunk_overlap: int):

    # Return smaller chunks of pages as list of LangChain Document objects again 
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""], # In decreasing order of priority
    )
    chunks = splitter.split_documents(pages)
    print(f"[LOGGING] Split into {len(chunks)} chunk(s)")
    return chunks


def build_vectorstore(chunks, embedding_model: str):

    # Generate vector embeddings with locally stored embedding model 
    print(f"[LOGGING] Loading embedding model: {embedding_model}")
    embedding_model = HuggingFaceEmbeddings(model_name=embedding_model) # Downloaded in C:\Users\<your_username>\.cache\huggingface\hub\ when run first time

    # Generate the indexed FAISS vector store in memory
    print("[LOGGING] Embedding chunks and building FAISS index...")
    vectorstore = FAISS.from_documents(chunks, embedding_model)
    return vectorstore


def persist_vectorstore(vectorstore: FAISS, kb_dir: str, index_name: str):

    # Persist the vectorstore in knowledge base
    os.makedirs(kb_dir, exist_ok=True)
    vectorstore.save_local(folder_path=kb_dir, index_name=index_name) # Generates index.faiss and also index.pkl
    print(f"[LOGGING] Saved FAISS index to {kb_dir}/{index_name}.faiss")


def persist_metadata(chunks, metadata_path: str):

    # Generate metadata.pkl
    metadata = [
        {
            "chunk_id": i,
            "source": doc.metadata.get("source"),
            "page": doc.metadata.get("page"),
            "content_preview": doc.page_content[:200],
        }
        for i, doc in enumerate(chunks)
    ]
    with open(metadata_path, "wb") as f:
        pickle.dump(metadata, f)
    print(f"[LOGGING] Saved metadata to {metadata_path}")


def main():
    pages = load_pdf(PDF_FILE)

    chunks = chunk_documents(pages, CHUNK_SIZE, CHUNK_OVERLAP)

    vectorstore = build_vectorstore(chunks, EMBEDDING_MODEL)

    persist_vectorstore(vectorstore, KB_DIR, INDEX_NAME)

    persist_metadata(chunks, METADATA_PATH)

    print("[LOGGING] Done.")


if __name__ == "__main__":
    main()