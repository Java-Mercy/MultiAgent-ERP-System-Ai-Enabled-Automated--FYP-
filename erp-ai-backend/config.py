"""
config.py — Centralized configuration loaded from .env via python-dotenv.
All modules import from here; never read os.environ directly in agents.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Groq LLM
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # Odoo XML-RPC
    ODOO_URL: str = os.getenv("ODOO_URL", "http://localhost:8069")
    ODOO_DB: str = os.getenv("ODOO_DB", "odoo")
    ODOO_USERNAME: str = os.getenv("ODOO_USERNAME", "admin")
    ODOO_PASSWORD: str = os.getenv("ODOO_PASSWORD", "admin")

    # Pinecone
    PINECONE_API_KEY: str = os.getenv("PINECONE_API_KEY", "")
    PINECONE_INDEX_NAME: str = os.getenv("PINECONE_INDEX_NAME", "crm-knowledge")
    PINECONE_DIMENSION: int = 384  # all-MiniLM-L6-v2 embedding dimension

    # HuggingFace Embeddings
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # App
    APP_TITLE: str = "Multi-Agent ERP AI Backend"
    APP_VERSION: str = "1.0.0"
    CORS_ORIGINS: list = ["*"]


settings = Settings()
