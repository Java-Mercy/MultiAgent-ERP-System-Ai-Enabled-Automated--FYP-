"""
rag/knowledge_loader.py — One-time script to load knowledge_docs/ into Pinecone.

Run with:
    cd erp-ai-backend && python -m rag.knowledge_loader

What it does:
  1. Reads all .txt files from knowledge_docs/
  2. Splits them into overlapping 500-char chunks
  3. Embeds with HuggingFace all-MiniLM-L6-v2
  4. Upserts into the Pinecone 'crm-knowledge' index
"""

import logging
import os
import time
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

KNOWLEDGE_DOCS_DIR = Path(__file__).parent.parent / "knowledge_docs"


def load_documents() -> list[Document]:
    """Load all .txt files from knowledge_docs/ as LangChain Documents."""
    docs = []
    txt_files = list(KNOWLEDGE_DOCS_DIR.glob("*.txt"))

    if not txt_files:
        logger.warning(f"No .txt files found in {KNOWLEDGE_DOCS_DIR}")
        return docs

    for path in txt_files:
        content = path.read_text(encoding="utf-8").strip()
        doc = Document(
            page_content=content,
            metadata={"source": path.name, "category": path.stem},
        )
        docs.append(doc)
        logger.info(f"Loaded: {path.name} ({len(content)} chars)")

    return docs


def split_documents(docs: list[Document]) -> list[Document]:
    """Split documents into overlapping chunks for better retrieval."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    logger.info(f"Split {len(docs)} documents into {len(chunks)} chunks.")
    return chunks


def ensure_index(pc: Pinecone) -> None:
    """Create Pinecone index if it doesn't exist yet."""
    existing = [idx.name for idx in pc.list_indexes()]
    if settings.PINECONE_INDEX_NAME not in existing:
        logger.info(f"Creating Pinecone index '{settings.PINECONE_INDEX_NAME}' …")
        pc.create_index(
            name=settings.PINECONE_INDEX_NAME,
            dimension=settings.PINECONE_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        # Poll until ready
        for attempt in range(30):
            index_info = pc.describe_index(settings.PINECONE_INDEX_NAME)
            status = index_info.status
            is_ready = status.get("ready", False) if isinstance(status, dict) else getattr(status, "ready", False)
            if is_ready:
                logger.info("Index is ready.")
                break
            logger.info(f"Waiting for index … attempt {attempt + 1}/30")
            time.sleep(3)
    else:
        logger.info(f"Index '{settings.PINECONE_INDEX_NAME}' already exists.")


def main():
    if not settings.PINECONE_API_KEY:
        raise EnvironmentError("PINECONE_API_KEY is not set in .env")

    logger.info("=== CRM Knowledge Loader ===")

    # 1. Load raw docs
    docs = load_documents()
    if not docs:
        logger.error("No documents to load. Aborting.")
        return

    # 2. Split into chunks
    chunks = split_documents(docs)

    # 3. Initialise Pinecone
    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    ensure_index(pc)
    index = pc.Index(settings.PINECONE_INDEX_NAME)

    # 4. Embed with HuggingFace (free, local)
    logger.info("Loading HuggingFace embedding model (first run downloads ~90 MB) …")
    embeddings = HuggingFaceEmbeddings(
        model_name=settings.EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    # 5. Upsert into Pinecone
    logger.info(f"Upserting {len(chunks)} chunks into Pinecone …")
    vector_store = PineconeVectorStore(
        index=index,
        embedding=embeddings,
        text_key="text",
    )
    vector_store.add_documents(chunks)
    logger.info("=== Knowledge loading complete! ===")

    # 6. Quick sanity check
    logger.info("Running sanity check query …")
    results = vector_store.similarity_search("follow-up email for hesitant lead", k=2)
    for i, r in enumerate(results, 1):
        logger.info(f"  Result {i}: [{r.metadata.get('source')}] {r.page_content[:100]} …")


if __name__ == "__main__":
    main()
