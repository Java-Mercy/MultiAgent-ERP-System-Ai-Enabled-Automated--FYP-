# Multi-Agent Chat-Based Automated ERP System
### FAST-NUCES Final Year Project (FYP)

A production-quality multi-agent AI backend that connects to Odoo 17 CRM, uses Groq LLaMA 3.3 70B as the LLM, and grounds all communications in company policy via Pinecone RAG.

---

## Architecture

```
User / n8n
    │
    ▼
RouterAgent          ← classifies intent (QUERY / ACTION / ANALYSIS / COMMUNICATION)
    │
    ├── DataRetrieverAgent    ← READ  operations via OdooMCPClient
    ├── TaskExecutorAgent     ← WRITE operations via OdooMCPClient + ActionValidatorAgent
    └── CommunicationAgent    ← Email drafts + summaries via Pinecone RAG + Groq LLM
```

---

## Stack

| Layer | Technology |
|-------|-----------|
| LLM | Groq `llama-3.3-70b-versatile` via `langchain-groq` |
| Backend | FastAPI + Uvicorn |
| Odoo | XML-RPC via built-in `xmlrpc.client` |
| RAG | Pinecone (free tier) + HuggingFace `all-MiniLM-L6-v2` (384-dim) |
| Env | `python-dotenv` |

---

## Setup

### 1. Install dependencies
```bash
cd erp-ai-backend
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your keys
```

### 3. Load RAG knowledge base (one-time)
```bash
python -m rag.knowledge_loader
```
This embeds the 4 policy documents from `knowledge_docs/` into Pinecone.

### 4. Start the server
```bash
uvicorn main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

---

## API Endpoints

### `GET /api/status`
System health check.
```json
{
  "status": "ok",
  "odoo_connected": true,
  "llm_provider": "Groq",
  "model": "llama-3.3-70b-versatile",
  "agents": [...],
  "rag_status": "connected"
}
```

### `POST /api/chat`
Main chat endpoint for the Next.js frontend.
```json
// Request
{ "message": "Show me all high priority leads", "session_id": "user-123" }

// Response
{ "response": "...", "agent_used": "DataRetrieverAgent", "intent": "QUERY", "action_taken": null }
```

### `POST /api/analyze-lead`
n8n webhook — full lead analysis with priority, summary, and email draft.
```json
// Request
{ "lead_id": 5, "notes": "Client seemed hesitant about pricing" }

// Response
{ "response": "...", "priority": "High", "summary": "...", "email_draft": "..." }
```

### `POST /api/update-odoo-lead`
n8n webhook — writes AI results to Odoo custom fields.
```json
// Request
{ "lead_id": 5, "priority": "High", "summary": "...", "email_draft": "..." }
```

---

## Agents

| Agent | File | Responsibility |
|-------|------|---------------|
| RouterAgent | `agents/router_agent.py` | Classifies intent, dispatches to specialist |
| DataRetrieverAgent | `agents/data_retriever.py` | READ from Odoo (search, filter, get) |
| TaskExecutorAgent | `agents/task_executor.py` | WRITE to Odoo (create, update, delete) |
| ActionValidatorAgent | `agents/action_validator.py` | Validates schema before every write |
| CommunicationAgent | `agents/communication_agent.py` | Email drafts + summaries via RAG |

---

## RAG Pipeline

1. **Load** — `knowledge_loader.py` reads `.txt` files from `knowledge_docs/`
2. **Split** — 500-char chunks with 50-char overlap
3. **Embed** — HuggingFace `all-MiniLM-L6-v2` (384-dim, runs locally)
4. **Store** — Upserted into Pinecone index `crm-knowledge`
5. **Query** — CommunicationAgent queries Pinecone BEFORE every LLM call

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Groq API key |
| `ODOO_URL` | Odoo instance URL (default: http://localhost:8069) |
| `ODOO_DB` | Odoo database name |
| `ODOO_USERNAME` | Odoo admin username |
| `ODOO_PASSWORD` | Odoo admin password |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_INDEX_NAME` | Pinecone index name (default: crm-knowledge) |
