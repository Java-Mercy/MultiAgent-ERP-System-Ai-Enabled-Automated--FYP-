# Multi-Agent AI-Enabled Automated ERP System — FYP

> **Final Year Project (FYP) — FAST-NUCES**
> An intelligent, chat-driven ERP system powered by a multi-agent AI backend integrated with Odoo 17 CRM.

---

## Project Goal

The goal of this FYP is to build a **fully automated ERP system controlled by a single chat interface**. Instead of navigating complex ERP menus, a sales team member types a natural language message — and AI agents handle everything: reading data, creating/updating leads, drafting professional emails, and predicting lead priority — all grounded in company policy via a RAG (Retrieval-Augmented Generation) pipeline.

---

## Setup & Installation Guide

Follow these steps exactly to run the entire Multi-Agent ERP System on your local machine.

### Prerequisites
- **Docker Desktop** (running)
- **Python 3.11+**
- **Node.js 18+**
- **Git**

---

### Step 1: Clone the Repository
```bash
git clone https://github.com/Java-Mercy/MultiAgent-ERP-System-Ai-Enabled-Automated--FYP-.git
cd MultiAgent-ERP-System-Ai-Enabled-Automated--FYP-
```

### Step 2: Environment Variables (`.env`)
You need to provide your API keys for the AI agents (Groq) and Vector DB (Pinecone).

1. Navigate to the backend folder:
   ```bash
   cd erp-ai-backend
   ```
2. Create a `.env` file based on the example:
   ```bash
   cp .env.example .env
   ```
3. Open the `.env` file and fill in your keys:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   PINECONE_API_KEY=your_pinecone_api_key_here
   PINECONE_INDEX_NAME=crm-knowledge-384
   
   # Odoo Configuration (Default local Docker settings)
   ODOO_URL=http://localhost:8070
   ODOO_DB=odoo
   ODOO_USERNAME=odoo
   ODOO_PASSWORD=odoo
   ```

### Step 3: Start the Infrastructure (Odoo & n8n)
Go back to the root directory and start the Docker containers:
```bash
cd ..
docker compose up -d
```
- **Odoo** is now running at: `http://localhost:8070`
- **n8n** is now running at: `http://localhost:5678`

### Step 4: Odoo Developer Mode & Module Setup
Now we need to install the custom `crm_ai_assistant` module in Odoo.

1. Open `http://localhost:8070` in your browser.
2. Log in using `odoo` as email and `odoo` as password.
3. Go to **Settings** (App menu at top left).
4. Scroll to the very bottom and click **Activate the developer mode**.
5. Go to the **Apps** menu.
6. Click **Update Apps List** in the top menu bar, then click **Update** in the popup.
7. In the search bar, remove the `Apps` filter and search for **CRM AI Assistant**.
8. Click **Activate** (or **Install** / **Upgrade**) on the CRM AI Assistant card.

### Step 5: Start the AI Backend (FastAPI)
The backend powers all the multi-agent logic.

1. Open a new terminal and navigate to the backend:
   ```bash
   cd erp-ai-backend
   ```
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Load the RAG knowledge base into Pinecone (Only run this ONCE):
   ```bash
   python -m rag.knowledge_loader
   ```
4. Start the FastAPI server:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
- **Backend API** is now running at: `http://localhost:8000`

### Step 6: Start the Frontend Chat UI (Next.js)
The frontend provides the conversational interface.

1. Open a new terminal and navigate to the frontend:
   ```bash
   cd erp-chat-frontend
   ```
2. Install Node modules:
   ```bash
   npm install
   ```
3. Start the development server:
   ```bash
   npm run dev
   ```
- **Chat UI** is now running at: `http://localhost:3000`
*(Note: Odoo will automatically embed this URL in the CRM menu under "AI Chat Assistant" thanks to the custom module!)*

### Step 7: Setup n8n Webhook & Odoo Automation
To make Odoo trigger the AI analysis automatically when a lead is created:

#### A. Set up the n8n Workflow
1. Open n8n at `http://localhost:5678`.
2. Create a new workflow.
3. Add a **Webhook** node:
   - Method: `POST`
   - Path: `analyze-lead`
   - Respond: `Immediately`
   - Copy the **Test URL** or **Production URL** (e.g., `http://n8n:5678/webhook/analyze-lead`).
4. Add an **HTTP Request** node connected to the Webhook:
   - Method: `POST`
   - URL: `http://host.docker.internal:8000/api/analyze-lead` *(This points to your FastAPI backend)*
   - Send Body: `True`
   - Body Parameters: Extract the `lead_id` and `notes` from the incoming Webhook payload.
5. Save and activate the workflow.

#### B. Set up the Odoo Automated Action
1. In Odoo (with Developer Mode active), go to **Settings** → **Technical** → **Automation** → **Automated Actions**.
2. Click **New**.
3. **Action Name**: Trigger AI Lead Analysis
4. **Model**: `Lead/Opportunity` (`crm.lead`)
5. **Action To Do**: `Send Webhook Notification`
6. **Trigger**: `On Creation & Update`
7. **URL**: Paste your n8n Webhook URL here.
8. Save the automated action.

---

🎉 **You're all set!** 
Try creating a lead in Odoo CRM, wait 5 seconds, and watch the AI automatically fill in the priority, summary, and email draft! Or open the **AI Chat Assistant** menu and start typing commands.

---

## Architecture Overview

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
│  ┌─────────────┐                                                │
│  │ RouterAgent │ — classifies intent, dispatches to specialist  │
│  └──────┬──────┘                                               │
│         ├──── QUERY      → DataRetrieverAgent                  │
│         ├──── ACTION     → TaskExecutorAgent                   │
│         ├──── ANALYSIS   → CommunicationAgent                  │
│         └──── COMMUNICATION → CommunicationAgent               │
└────────────┬───────────────────────┬────────────────────────────┘
             │                       │
             ▼                       ▼
┌────────────────────┐   ┌───────────────────────────────────────┐
│  Odoo 17 CRM       │   │  RAG Pipeline                         │
│  (Docker :8070)    │   │  Pinecone (crm-knowledge-384 index)   │
└────────────────────┘   └───────────────────────────────────────┘
```

## Agents Used
- **RouterAgent**: Classifies intent (via LangChain & Groq) and routes the request.
- **DataRetrieverAgent**: Reads data from Odoo.
- **TaskExecutorAgent**: Creates, updates, and deletes CRM leads.
- **ActionValidatorAgent**: Validates operations before execution.
- **CommunicationAgent**: Generates emails and analyses by querying Pinecone RAG policies.
