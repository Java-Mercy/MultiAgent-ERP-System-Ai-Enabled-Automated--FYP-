# Multi-Agent AI-Enabled Automated ERP System — FYP

> **Final Year Project (FYP) — FAST-NUCES**
> An intelligent, chat-driven ERP system powered by a multi-agent AI backend integrated with Odoo 17 CRM.

---

## Project Goal

The goal of this FYP is to build a **fully automated ERP system controlled by a single chat interface**. Instead of navigating complex ERP menus, a sales team member types a natural language message — and AI agents handle everything: reading data, creating/updating leads, drafting professional emails, and predicting lead priority — all grounded in company policy via a RAG (Retrieval-Augmented Generation) pipeline.

**One chat interface. One AI brain. Full ERP automation.**

---

## What We've Built So Far

### ✅ Requirement A — Automated Lead Intelligence Pipeline (COMPLETE & TESTED)

When a lead is created or updated in Odoo CRM with notes/description:

1. **Odoo Automated Action** fires a webhook to n8n
2. **n8n** receives the event and calls FastAPI `/api/analyze-lead`
3. **FastAPI Multi-Agent System** processes the lead:
   - **RouterAgent** classifies the intent and routes to the right specialist
   - **DataRetrieverAgent** fetches the lead's full data from Odoo via XML-RPC
   - **CommunicationAgent** queries **Pinecone RAG** for company email policy and lead scoring rules
   - **Groq LLM** (llama-3.3-70b-versatile) generates structured analysis
4. Results are **written back to Odoo** automatically — no human needed:
   - `ai_priority_prediction` — High / Medium / Low (based on budget, urgency, competition)
   - `ai_summary` — 2-3 sentence executive summary of the lead
   - `ai_email_draft` — Professional, policy-grounded email ready to send

The salesperson opens the lead, sees the **AI Assistant tab** pre-filled — and can send a follow-up in seconds.

**Verified test results (3 leads):**

| Lead | Notes | AI Priority | Correct? |
|------|-------|------------|----------|
| Sarah Johnson — HomeFirst Realty | $8K budget, 2-week deadline, competitor involved | **High** | ✅ |
| Mike Chen — TechWave Solutions | $3K budget, next quarter, referral | **Medium** | ✅ |
| Lisa Park — Browsing Inquiry | No budget, just exploring | **Low** | ✅ |

### ✅ Requirement B — Chat Interface (In Progress)

A Next.js frontend allows users to chat naturally with the ERP system:
- "Show me all high-priority leads"
- "Create a lead for ACME Corp with a $10,000 budget"
- "Draft a follow-up email for lead #5"
- "Analyze and prioritize lead #7"

### ✅ Custom Odoo Module — `crm_ai_assistant`

A custom Odoo 17 addon that adds three new fields to every CRM lead:
- **AI Summary** (Text) — agent-generated summary
- **AI Predicted Priority** (Selection: High/Medium/Low) — agent-scored
- **AI Email Draft** (HTML) — ready-to-send email

Displayed in a new **"AI Assistant" tab** in the lead form view.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACES                          │
│  Next.js Chat Frontend (:3000)    Odoo CRM UI (:8070)          │
└────────────────────┬────────────────────┬───────────────────────┘
                     │ /api/chat          │ Automated Action
                     ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    n8n WORKFLOW ENGINE (:5678)                  │
│  Receives Odoo webhooks → routes to FastAPI endpoints           │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FastAPI MULTI-AGENT BACKEND (:8000)            │
│                                                                 │
│  ┌─────────────┐                                                │
│  │ RouterAgent │ — classifies intent, dispatches to specialist  │
│  └──────┬──────┘                                               │
│         ├──── QUERY      → DataRetrieverAgent                  │
│         ├──── ACTION     → TaskExecutorAgent                   │
│         ├──── ANALYSIS   → CommunicationAgent                  │
│         └──── COMMUNICATION → CommunicationAgent               │
│                                                                 │
│  All agents log which agent handled the request                 │
└────────────┬───────────────────────┬────────────────────────────┘
             │                       │
             ▼                       ▼
┌────────────────────┐   ┌───────────────────────────────────────┐
│  Odoo 17 CRM       │   │  RAG Pipeline                         │
│  (Docker :8070)    │   │  Pinecone (crm-knowledge-384 index)   │
│  XML-RPC API       │   │  HuggingFace all-MiniLM-L6-v2 (384d) │
│  PostgreSQL DB     │   │  4 knowledge docs loaded (26 vectors) │
└────────────────────┘   └───────────────────────────────────────┘
                                       │
                                       ▼
                         ┌─────────────────────────┐
                         │  Groq Cloud LLM         │
                         │  llama-3.3-70b-versatile│
                         └─────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Python 3.11+ |
| Agents | LangChain (RouterAgent, DataRetrieverAgent, TaskExecutorAgent, ActionValidatorAgent, CommunicationAgent) |
| LLM | Groq Cloud — llama-3.3-70b-versatile |
| ERP | Odoo 17 (Docker) + PostgreSQL |
| Odoo Integration | Python `xmlrpc.client` (built-in, no extra libs) |
| RAG Vector Store | Pinecone (free tier, serverless, us-east-1) |
| RAG Embeddings | HuggingFace all-MiniLM-L6-v2 (384-dim, runs locally) |
| Workflow Automation | n8n (Docker) |
| Frontend | Next.js App Router + Tailwind CSS + NextAuth |
| Config | python-dotenv |

---

## Project Structure

```
FYP-Claude-Code/
├── docker-compose.yml              # Odoo 17 + PostgreSQL + n8n
├── erp-ai-backend/                 # FastAPI multi-agent backend
│   ├── main.py                     # FastAPI app, all endpoints
│   ├── config.py                   # Centralized config from .env
│   ├── requirements.txt
│   ├── agents/
│   │   ├── router_agent.py         # Agent 1: intent classifier + dispatcher
│   │   ├── data_retriever.py       # Agent 2: reads leads from Odoo
│   │   ├── task_executor.py        # Agent 3: creates/updates/deletes leads
│   │   ├── action_validator.py     # Agent 4: validates before write
│   │   └── communication_agent.py  # Agent 5: RAG-grounded email + analysis
│   ├── mcp/
│   │   └── odoo_mcp_client.py      # XML-RPC wrapper — all Odoo access goes here
│   ├── rag/
│   │   ├── pinecone_store.py       # Pinecone index connection + query interface
│   │   └── knowledge_loader.py     # Loads knowledge docs into Pinecone
│   └── knowledge_docs/             # Company policy documents for RAG
│       ├── lead_scoring_policy.txt  # High/Medium/Low priority rules
│       ├── email_templates.txt      # 4 email template types with structure
│       ├── follow_up_guidelines.txt
│       └── crm_best_practices.txt
├── odoo_custom_addons/
│   └── crm_ai_assistant/           # Custom Odoo 17 module
│       ├── __manifest__.py
│       ├── models/
│       │   └── crm_lead_ai.py      # Adds ai_summary, ai_priority_prediction, ai_email_draft
│       └── views/
│           └── crm_lead_ai_views.xml  # "AI Assistant" tab in lead form
└── config/                         # Odoo server config
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Health check — Odoo, RAG, LLM status |
| POST | `/api/analyze-lead` | n8n calls this — full AI analysis of a lead |
| POST | `/api/chat` | Frontend chat — natural language ERP control |
| POST | `/api/update-odoo-lead` | Writes AI results back to Odoo fields |

### Example: `/api/analyze-lead`
```json
POST /api/analyze-lead
{ "lead_id": 5, "notes": "Budget $8K, urgent, already talking to competitor" }

Response:
{
  "priority": "High",
  "summary": "Sarah Johnson has a confirmed $8K budget with an urgent 2-week deadline...",
  "email_draft": "Subject: AI Chatbot for Real Estate — Urgent Implementation\nDear Sarah...",
  "agent_used": "CommunicationAgent",
  "rag_context_used": true,
  "odoo_write": { "success": true, "fields_written": ["ai_priority_prediction", "ai_summary", "ai_email_draft"] }
}
```

---

## Running the Project

### Prerequisites
- Docker Desktop running
- Python 3.11+
- Node.js 18+ (for frontend)
- `.env` file in `erp-ai-backend/` with keys (see below)

### 1. Start Infrastructure (Odoo + n8n)
```bash
docker compose up -d
```
- Odoo: http://localhost:8070
- n8n: http://localhost:5678

### 2. Start FastAPI Backend
```bash
cd erp-ai-backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
API: http://localhost:8000 | Docs: http://localhost:8000/docs

### 3. Load RAG Knowledge Base (first time only)
```bash
cd erp-ai-backend
python -m rag.knowledge_loader
```

### 4. Install Odoo Custom Module
In Odoo: Settings → Apps → Update Apps List → search "CRM AI Assistant" → Install

### 5. Start Frontend
```bash
cd erp-chat-frontend
npm install
npm run dev
```
Frontend: http://localhost:3000

### Environment Variables (`.env`)
```env
GROQ_API_KEY=your_groq_api_key
ODOO_URL=http://localhost:8070
ODOO_DB=odoo
ODOO_USERNAME=your_odoo_email
ODOO_PASSWORD=your_odoo_password
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=crm-knowledge-384
```

---

## Agents — How They Work

### RouterAgent (Agent 1)
Every message goes through the RouterAgent first. It uses the LLM to classify intent into one of four categories:
- `QUERY` → reads data from Odoo
- `ACTION` → creates/updates/deletes records
- `ANALYSIS` → scores and evaluates a lead
- `COMMUNICATION` → drafts emails and summaries

Falls back to keyword-based classification if LLM is unavailable.

### DataRetrieverAgent (Agent 2)
Handles all read operations. Extracts lead IDs from natural language, builds Odoo domain filters, and returns LLM-formatted summaries of leads.

### TaskExecutorAgent (Agent 3)
Creates, updates, and deletes CRM leads. Works through ActionValidatorAgent for confirmation before destructive writes.

### ActionValidatorAgent (Agent 4)
Acts as a safety layer — validates write operations before they're executed in Odoo.

### CommunicationAgent (Agent 5)
The most powerful agent. **Must query Pinecone before generating any email or analysis.** Retrieves relevant chunks from the company knowledge base (lead scoring rules, email templates, follow-up guidelines) and passes them as grounding context to the LLM. Produces:
- Priority prediction (High/Medium/Low) with reasoning
- 2-3 sentence executive summary
- Complete, personalized email draft with subject line

---

## RAG Knowledge Base

Four company policy documents loaded into Pinecone (26 vectors, 384-dim):

| Document | Purpose |
|----------|---------|
| `lead_scoring_policy.txt` | Rules for High/Medium/Low priority: budget thresholds, urgency signals |
| `email_templates.txt` | 4 email types: First Contact, Follow-Up, Closing, Re-Engagement |
| `follow_up_guidelines.txt` | When and how to follow up with leads |
| `crm_best_practices.txt` | General CRM usage and sales process guidelines |

---

## What's Next (Roadmap)

- [ ] **Frontend Chat UI** — Next.js chat interface fully wired to `/api/chat`
- [ ] **NextAuth authentication** — Secure the chat frontend
- [ ] **Bulk lead analysis** — Analyze all pending leads in one command
- [ ] **Email sending integration** — Send drafted emails directly from chat
- [ ] **Dashboard** — Real-time view of AI predictions and lead pipeline
- [ ] **Action history log** — Track every agent action for audit trail

---

## Team

**FYP Project — FAST-NUCES**
Multi-Agent Chat-Based Automated ERP System
