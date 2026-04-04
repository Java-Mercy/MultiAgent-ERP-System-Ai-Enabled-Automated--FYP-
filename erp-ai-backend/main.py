"""
main.py — FastAPI application entry point.
Registers all routes, CORS middleware, and wires up agents.
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from config import settings
from agents.router_agent import RouterAgent
from mcp.odoo_mcp_client import OdooMCPClient

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description="Multi-Agent Chat-Based Automated ERP System — FAST-NUCES FYP",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared singletons (initialized once at startup) ───────────────────────────
odoo_client = OdooMCPClient()
router_agent = RouterAgent()
# Use the pinecone store already inside router_agent — avoids loading embeddings twice
pinecone_store = router_agent._pinecone


# ── Request / Response models ─────────────────────────────────────────────────
class AnalyzeLeadRequest(BaseModel):
    lead_id: int
    notes: Optional[str] = ""


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class UpdateOdooLeadRequest(BaseModel):
    lead_id: int
    priority: Optional[str] = None
    summary: Optional[str] = None
    email_draft: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    """System health check — verifies Odoo connectivity, LLM config, and RAG."""
    logger.info("Health check requested")

    odoo_connected = False
    try:
        odoo_client.authenticate()
        odoo_connected = True
    except Exception as e:
        logger.warning(f"Odoo connectivity check failed: {e}")

    rag_status = "unavailable"
    try:
        if pinecone_store.index is not None:
            rag_status = "connected"
    except Exception as e:
        logger.warning(f"RAG status check failed: {e}")

    return {
        "status": "ok",
        "odoo_connected": odoo_connected,
        "llm_provider": "Groq",
        "model": settings.GROQ_MODEL,
        "agents": [
            "RouterAgent",
            "DataRetrieverAgent",
            "TaskExecutorAgent",
            "ActionValidatorAgent",
            "CommunicationAgent",
        ],
        "rag_status": rag_status,
    }


@app.post("/api/analyze-lead")
async def analyze_lead(request: AnalyzeLeadRequest):
    """
    n8n webhook endpoint.
    1. Communication Agent uses RAG → generates priority, summary, email_draft.
    2. Writes results back to the crm_ai_assistant custom fields in Odoo.
    3. Returns the AI analysis + write confirmation.
    """
    logger.info(f"[/api/analyze-lead] lead_id={request.lead_id}")
    try:
        message = (
            f"Analyze lead #{request.lead_id}. "
            f"Additional notes: {request.notes or 'none'}. "
            "Draft a professional follow-up email and assign a priority (High/Medium/Low)."
        )
        result = await router_agent.handle(
            message=message,
            session_id=f"analyze-{request.lead_id}",
            context={"lead_id": request.lead_id, "notes": request.notes},
        )

        # Write AI-generated values back to Odoo custom fields
        priority   = result.get("priority")
        summary    = result.get("summary")
        email_draft = result.get("email_draft")

        odoo_write: dict = {"attempted": False}
        if any([priority, summary, email_draft]):
            try:
                odoo_write = odoo_client.update_ai_fields(
                    lead_id=request.lead_id,
                    priority=priority,
                    summary=summary,
                    email_draft=email_draft,
                )
                odoo_write["attempted"] = True
                logger.info(
                    f"[/api/analyze-lead] AI fields written to Odoo — "
                    f"lead #{request.lead_id}, fields={odoo_write.get('fields_written')}"
                )
            except RuntimeError as e:
                # Module not installed — non-fatal, still return AI result
                logger.warning(f"[/api/analyze-lead] Could not write AI fields: {e}")
                odoo_write = {"attempted": True, "success": False, "error": str(e)}
            except Exception as e:
                logger.error(f"[/api/analyze-lead] Odoo write error: {e}", exc_info=True)
                odoo_write = {"attempted": True, "success": False, "error": str(e)}

        result["odoo_write"] = odoo_write
        return result

    except Exception as e:
        logger.error(f"[/api/analyze-lead] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Frontend chat endpoint.
    Router Agent classifies intent and delegates to the correct specialist agent.
    """
    logger.info(f"[/api/chat] session={request.session_id} | message={request.message[:80]}")
    try:
        result = await router_agent.handle(
            message=request.message,
            session_id=request.session_id,
        )
        return result
    except Exception as e:
        logger.error(f"[/api/chat] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/update-odoo-lead")
async def update_odoo_lead(request: UpdateOdooLeadRequest):
    """
    n8n webhook — writes AI-generated results to the crm_ai_assistant custom fields.

    Receives: {lead_id, priority?, summary?, email_draft?}
    Returns:  {success, lead_id, fields_written, field_map}
    """
    logger.info(f"[/api/update-odoo-lead] lead_id={request.lead_id}")

    if not any([request.priority, request.summary, request.email_draft]):
        return {"success": False, "message": "No fields provided to update."}

    try:
        result = odoo_client.update_ai_fields(
            lead_id=request.lead_id,
            priority=request.priority,
            summary=request.summary,
            email_draft=request.email_draft,
        )
        return result
    except RuntimeError as e:
        # Module not installed
        logger.error(f"[/api/update-odoo-lead] {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[/api/update-odoo-lead] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
