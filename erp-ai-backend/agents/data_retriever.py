"""
agents/data_retriever.py — Agent 2: Data Retriever

Handles all READ operations against Odoo CRM:
  - "show leads", "list all leads"
  - "search leads by name"
  - "get lead #5"
  - "filter by priority / stage"

Uses OdooMCPClient — never calls xmlrpc directly.
"""

import logging
import re
from typing import Any, Optional

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings
from mcp.odoo_mcp_client import OdooMCPClient

logger = logging.getLogger(__name__)
AGENT_NAME = "DataRetrieverAgent"


class DataRetrieverAgent:
    """
    Retrieves CRM lead data from Odoo and formats it for the user.
    """

    def __init__(self):
        self._odoo = OdooMCPClient()
        self._llm = ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            temperature=0.2,
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    def handle(self, message: str, context: Optional[dict] = None) -> dict:
        """
        Route the retrieval request and return a formatted response.

        Args:
            message: User's natural language query.
            context: Optional dict with pre-parsed fields like {"lead_id": 5}.

        Returns:
            {"response": str, "agent_used": str, "data": list|dict}
        """
        logger.info(f"[{AGENT_NAME}] Handling: {message[:80]}")

        try:
            # Check if a specific lead ID is mentioned
            lead_id = self._extract_lead_id(message, context)

            if lead_id:
                return self._get_single_lead(lead_id, message)

            # Check for name-based search
            name_query = self._extract_name_query(message)
            if name_query:
                return self._search_by_name(name_query, message)

            # Default: list/filter leads
            return self._list_leads(message)

        except Exception as e:
            logger.error(f"[{AGENT_NAME}] Error: {e}", exc_info=True)
            return {
                "response": f"I encountered an error while retrieving data from Odoo: {str(e)}",
                "agent_used": AGENT_NAME,
                "data": [],
            }

    # ── Retrieval methods ─────────────────────────────────────────────────────

    def _get_single_lead(self, lead_id: int, message: str) -> dict:
        logger.info(f"[{AGENT_NAME}] Fetching lead #{lead_id}")
        lead = self._odoo.read_lead(lead_id)
        formatted = self._format_lead(lead)
        summary = self._llm_summarize(message, [lead])
        return {
            "response": summary,
            "agent_used": AGENT_NAME,
            "data": lead,
            "formatted": formatted,
        }

    def _search_by_name(self, name: str, message: str) -> dict:
        logger.info(f"[{AGENT_NAME}] Searching leads by name: '{name}'")
        leads = self._odoo.search_leads_by_name(name, limit=10)
        if not leads:
            return {
                "response": f"No leads found matching '{name}'.",
                "agent_used": AGENT_NAME,
                "data": [],
            }
        summary = self._llm_summarize(message, leads)
        return {
            "response": summary,
            "agent_used": AGENT_NAME,
            "data": leads,
            "count": len(leads),
        }

    def _list_leads(self, message: str) -> dict:
        """List leads, optionally applying filters inferred from the message."""
        domain = self._build_domain_from_message(message)
        logger.info(f"[{AGENT_NAME}] Listing leads with domain: {domain}")
        leads = self._odoo.search_leads(domain=domain, limit=20)
        if not leads:
            return {
                "response": "No leads found in Odoo matching your request.",
                "agent_used": AGENT_NAME,
                "data": [],
            }
        summary = self._llm_summarize(message, leads)
        return {
            "response": summary,
            "agent_used": AGENT_NAME,
            "data": leads,
            "count": len(leads),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_lead_id(self, message: str, context: Optional[dict]) -> Optional[int]:
        """Extract a lead ID from context dict or message text."""
        if context and context.get("lead_id"):
            return int(context["lead_id"])
        # Match patterns like "lead #5", "lead 5", "#12", "id 42"
        patterns = [r"lead\s*#(\d+)", r"#(\d+)", r"\blead\s+(\d+)\b", r"\bid\s*[=:]?\s*(\d+)\b"]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def _extract_name_query(self, message: str) -> Optional[str]:
        """Extract a name search term from phrases like 'search for ACME' or 'find leads named John'."""
        patterns = [
            r"(?:search|find|look for|get)\s+(?:lead[s]?\s+)?(?:named?|for|called|about)?\s+[\"']?([A-Za-z0-9 &.,'-]+)[\"']?",
            r"leads?\s+(?:named?|for|about|from)\s+[\"']?([A-Za-z0-9 &.,'-]+)[\"']?",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                term = match.group(1).strip()
                if len(term) >= 2:
                    return term
        return None

    def _build_domain_from_message(self, message: str) -> list:
        """Infer Odoo domain filters from natural language."""
        domain = []
        msg_lower = message.lower()

        # Priority filters
        if any(w in msg_lower for w in ["high priority", "urgent", "high-priority"]):
            domain.append(["priority", "=", "2"])
        elif any(w in msg_lower for w in ["medium priority", "medium-priority"]):
            domain.append(["priority", "=", "1"])
        elif any(w in msg_lower for w in ["low priority", "low-priority"]):
            domain.append(["priority", "=", "0"])

        return domain

    def _format_lead(self, lead: dict) -> str:
        """Format a single lead as a readable string."""
        lines = [
            f"Lead #{lead.get('id')} — {lead.get('name', 'Unnamed')}",
            f"  Contact : {lead.get('partner_name', 'N/A')}",
            f"  Email   : {lead.get('email_from', 'N/A')}",
            f"  Phone   : {lead.get('phone', 'N/A')}",
            f"  Stage   : {lead.get('stage_id', ['', 'N/A'])[1] if isinstance(lead.get('stage_id'), list) else 'N/A'}",
            f"  Revenue : ${lead.get('expected_revenue', 0):,.2f}",
            f"  Priority: {lead.get('priority', '0')}",
        ]
        if lead.get("description"):
            lines.append(f"  Notes   : {str(lead['description'])[:200]}")
        return "\n".join(lines)

    def _llm_summarize(self, user_query: str, leads: list[dict]) -> str:
        """Use LLM to produce a natural language summary of the retrieved leads."""
        leads_text = "\n\n".join(self._format_lead(l) for l in leads[:10])
        messages = [
            SystemMessage(content=(
                "You are a CRM data assistant. The user asked a question and you retrieved "
                "the following leads from Odoo. Provide a clear, concise answer. "
                "Present lead information in a readable format. Be factual."
            )),
            HumanMessage(content=(
                f"User query: {user_query}\n\n"
                f"Retrieved leads:\n{leads_text}\n\n"
                f"Total leads retrieved: {len(leads)}"
            )),
        ]
        try:
            response = self._llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"[{AGENT_NAME}] LLM summarise failed: {e}")
            return f"Retrieved {len(leads)} lead(s).\n\n" + leads_text
