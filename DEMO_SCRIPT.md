# Final Year Project (FYP) 

## Part 1 — Architecture (2 min)
- Show architecture diagram. 
- **Talking points:** "4 agents, hybrid RAG, MCP, n8n automation."

## Part 2 — Teacher's Requirement (5 min)
- Open Odoo CRM.
- Create a lead with detailed notes.
- Save → wait 5 seconds.
- Open the lead → show AI Assistant tab auto-populated.
- **Talking points:** "This happened automatically via n8n triggering our AI agents."

## Part 3 — Interactive Chat (5 min)
- Click "AI Chat Assistant" in Odoo menu (embedded).
- Demo the following flow:
  1. "Show all leads"
  2. "Create lead for Dr. Ali, MedTech, ali@medtech.pk"
  3. "Draft follow-up email for the new lead"
  4. "Show high priority leads"
  5. "Summarize lead 1"
- Point out agent badges on each response to show multi-agent collaboration.

## Part 4 — Security & Audit (2 min)
- Show activity log sidebar.
- Change role to "user" → try to delete a record → show RBAC blocking the action.
- Show `/api/audit-log` endpoint.

## Part 5 — Viva Answers
- **Why Groq?** Free, fastest, open-source model, SRS says avoid paid APIs.
- **Why hybrid RAG?** Structured data = direct query, unstructured = Pinecone.
- **What is MCP?** Open standard for secure AI-to-ERP communication.
- **Why 4 agents?** Specialization, audit trail, security.

## BACKUP PLAN
If anything fails during the demo, manually call `/api/analyze-lead` via curl:
```bash
curl -X POST http://localhost:8000/api/analyze-lead \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1, "notes": "Test notes"}'
```