"""
main.py — FastAPI application entry point.
Registers all routes, CORS middleware, and wires up agents.
"""

import time
import logging
from typing import Any, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from agents.router_agent import RouterAgent
from mcp.odoo_mcp_client import OdooMCPClient
from audit.audit_logger import get_audit_logger

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Startup time for uptime ──────────────────────────────────────────────────
START_TIME = time.time()


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
_audit = get_audit_logger()


def _normalize_role(role: Optional[str]) -> str:
    r = (role or "admin").strip().lower()
    return r if r in ("admin", "user") else "admin"


def _audit_from_result(result: Any) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(result, dict):
        return None, None
    agent = result.get("agent_used")
    if not isinstance(agent, str):
        agent = None
    rid = result.get("lead_id")
    record = str(rid) if rid is not None else None
    return agent, record


# ── Request / Response models ─────────────────────────────────────────────────
class AnalyzeLeadRequest(BaseModel):
    lead_id: int
    notes: Optional[str] = ""
    role: Optional[str] = Field(default="admin", description='"admin" or "user"')


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    role: Optional[str] = Field(default="admin", description='"admin" or "user"')


class UpdateOdooLeadRequest(BaseModel):
    lead_id: int
    priority: Optional[str] = None
    summary: Optional[str] = None
    email_draft: Optional[str] = None
    role: Optional[str] = Field(default="admin", description='"admin" or "user"')


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    """System health check — verifies Odoo connectivity, LLM config, and RAG."""
    logger.info("Health check requested")
    action_type = "GET /api/status"
    session_id = ""

    odoo_connected = False
    try:
        odoo_client.authenticate()
        odoo_connected = True
    except Exception as e:
        logger.warning(f"Odoo connectivity check failed: {e}")

    pinecone_connected = False
    try:
        if pinecone_store.index is not None:
            pinecone_connected = True
    except Exception as e:
        logger.warning(f"RAG status check failed: {e}")

    groq_connected = bool(settings.GROQ_API_KEY)

    try:
        daily_summary = _audit.daily_summary()
        total_actions = daily_summary.get("total_actions", 0)
    except Exception:
        total_actions = 0

    uptime_seconds = int(time.time() - START_TIME)

    overall_status = "ok" if (odoo_connected and pinecone_connected and groq_connected) else "partial"
    if not (odoo_connected or pinecone_connected or groq_connected):
        overall_status = "error"

    result = {
        "status": overall_status,
        "odoo_connected": odoo_connected,
        "pinecone_connected": pinecone_connected,
        "groq_connected": groq_connected,
        "llm_model": settings.GROQ_MODEL,
        "agents_list": [
            "RouterAgent",
            "DataRetrieverAgent",
            "TaskExecutorAgent",
            "ActionValidatorAgent",
            "CommunicationAgent",
        ],
        "total_actions_today": total_actions,
        "uptime_seconds": uptime_seconds,
    }
    st = "success" if odoo_connected else "error"
    err = None if odoo_connected else "Odoo not reachable"
    _audit.log_api_call(
        session_id=session_id,
        action_type=action_type,
        agent_used="system",
        record_id=None,
        status=st,
        error_message=err,
    )
    return result


@app.post("/api/analyze-lead")
async def analyze_lead(request: AnalyzeLeadRequest):
    """
    n8n webhook endpoint.
    1. Communication Agent uses RAG → generates priority, summary, email_draft.
    2. Writes results back to the crm_ai_assistant custom fields in Odoo.
    3. Returns the AI analysis + write confirmation.
    """
    action_type = "POST /api/analyze-lead"
    session_id = f"analyze-{request.lead_id}"
    role = _normalize_role(request.role)
    logger.info(f"[/api/analyze-lead] lead_id={request.lead_id} role={role}")

    try:
        message = (
            f"Analyze lead #{request.lead_id}. "
            f"Additional notes: {request.notes or 'none'}. "
            "Draft a professional follow-up email and assign a priority (High/Medium/Low)."
        )
        result = await router_agent.handle(
            message=message,
            session_id=session_id,
            context={"lead_id": request.lead_id, "notes": request.notes},
            role=role,
        )

        # Write AI-generated values back to Odoo custom fields
        priority = result.get("priority")
        summary = result.get("summary")
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
                logger.warning(f"[/api/analyze-lead] Could not write AI fields: {e}")
                odoo_write = {"attempted": True, "success": False, "error": str(e)}
            except Exception as e:
                logger.error(f"[/api/analyze-lead] Odoo write error: {e}", exc_info=True)
                odoo_write = {
                    "attempted": True,
                    "success": False,
                    "error": f"Odoo could not save AI fields: {str(e)}",
                }

        result["odoo_write"] = odoo_write
        ag, rid = _audit_from_result(result)
        ow_ok = odoo_write.get("success", True) if isinstance(odoo_write, dict) else True
        st = "success" if ow_ok and not odoo_write.get("error") else "error"
        err_msg = None
        if isinstance(odoo_write, dict) and odoo_write.get("error"):
            err_msg = str(odoo_write.get("error"))
        _audit.log_api_call(
            session_id=session_id,
            action_type=action_type,
            agent_used=ag,
            record_id=str(request.lead_id),
            status=st,
            error_message=err_msg,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[/api/analyze-lead] Error: {e}", exc_info=True)
        _audit.log_api_call(
            session_id=session_id,
            action_type=action_type,
            agent_used=None,
            record_id=str(request.lead_id),
            status="error",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Frontend chat endpoint.
    Router Agent classifies intent and delegates to the correct specialist agent.
    """
    role = _normalize_role(request.role)
    sid = request.session_id or "default"
    action_type = "POST /api/chat"
    logger.info(f"[/api/chat] session={sid} role={role} | message={request.message[:80]}")

    try:
        result = await router_agent.handle(
            message=request.message,
            session_id=sid,
            role=role,
        )
        ag, rid = _audit_from_result(result)
        at = result.get("action_taken")
        err = result.get("response") if at in ("error", "odoo_write_failed") else None
        st = "error" if at in ("error", "odoo_write_failed") else "success"
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used=ag,
            record_id=rid,
            status=st,
            error_message=err if st == "error" else None,
        )
        return result
    except Exception as e:
        logger.error(f"[/api/chat] Error: {e}", exc_info=True)
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used=None,
            record_id=None,
            status="error",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/update-odoo-lead")
async def update_odoo_lead(request: UpdateOdooLeadRequest):
    """
    n8n webhook — writes AI-generated results to the crm_ai_assistant custom fields.

    Receives: {lead_id, priority?, summary?, email_draft?}
    Returns:  {success, lead_id, fields_written, field_map}
    """
    action_type = "POST /api/update-odoo-lead"
    sid = ""
    logger.info(f"[/api/update-odoo-lead] lead_id={request.lead_id}")

    role = _normalize_role(request.role)
    if role != "admin":
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used="ActionValidatorAgent",
            record_id=str(request.lead_id),
            status="error",
            error_message="Forbidden: admin role required",
        )
        raise HTTPException(status_code=403, detail="Admin role required for this endpoint.")

    if not any([request.priority, request.summary, request.email_draft]):
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used="system",
            record_id=str(request.lead_id),
            status="error",
            error_message="No fields provided",
        )
        return {"success": False, "message": "No fields provided to update."}

    try:
        result = odoo_client.update_ai_fields(
            lead_id=request.lead_id,
            priority=request.priority,
            summary=request.summary,
            email_draft=request.email_draft,
        )
        st = "success" if result.get("success") else "error"
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used="OdooMCPClient",
            record_id=str(request.lead_id),
            status=st,
            error_message=None if st == "success" else "update_ai_fields failed",
        )
        return result
    except RuntimeError as e:
        logger.error(f"[/api/update-odoo-lead] {e}")
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used="OdooMCPClient",
            record_id=str(request.lead_id),
            status="error",
            error_message=str(e),
        )
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[/api/update-odoo-lead] Error: {e}", exc_info=True)
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used="OdooMCPClient",
            record_id=str(request.lead_id),
            status="error",
            error_message=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Odoo could not update lead #{request.lead_id}: {str(e)}",
        )


@app.get("/api/audit-log")
async def audit_log(limit: int = Query(default=20, ge=1, le=500)):
    """Recent audit entries (newest first)."""
    action_type = "GET /api/audit-log"
    sid = ""
    try:
        rows = _audit.get_recent(limit)
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used="AuditLogger",
            record_id=None,
            status="success",
            error_message=None,
        )
        return {"entries": rows}
    except Exception as e:
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used=None,
            record_id=None,
            status="error",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/daily-summary")
async def daily_summary_report():
    """Aggregated audit counts for the current UTC day."""
    action_type = "GET /api/reports/daily-summary"
    sid = ""
    try:
        summary = _audit.daily_summary()
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used="AuditLogger",
            record_id=None,
            status="success",
            error_message=None,
        )
        return summary
    except Exception as e:
        _audit.log_api_call(
            session_id=sid,
            action_type=action_type,
            agent_used=None,
            record_id=None,
            status="error",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))
