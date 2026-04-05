"""
agents/task_executor.py — Agent 3: Task Executor

Handles all WRITE operations: create, update, delete leads.
ALWAYS calls ActionValidatorAgent before executing any write.
Uses OdooMCPClient — never calls xmlrpc directly.
"""

import logging
import re
from typing import Optional

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings
from mcp.odoo_mcp_client import OdooMCPClient
from agents.action_validator import ActionValidatorAgent

logger = logging.getLogger(__name__)
AGENT_NAME = "TaskExecutorAgent"

# Maps common natural-language field aliases to canonical Odoo field names.
# Used to normalize LLM output before validation.
FIELD_ALIASES: dict = {
    "email":        "email_from",
    "mail":         "email_from",
    "company":      "partner_name",
    "company_name": "partner_name",
    "contact":      "partner_name",
    "contact_name": "partner_name",
    "revenue":      "expected_revenue",
    "amount":       "expected_revenue",
    "value":        "expected_revenue",
    "notes":        "description",
    "note":         "description",
    "comment":      "description",
    "deal_name":    "name",
    "title":        "name",
}


class TaskExecutorAgent:
    """
    Executes CRM write operations after validation.

    Supported intents:
      - Create lead: "create a lead for ACME Corp worth $5000"
      - Update lead: "update lead #3, set priority to High"
      - Delete lead: "delete lead #7"
    """

    def __init__(self):
        self._odoo = OdooMCPClient()
        self._validator = ActionValidatorAgent()
        self._llm = ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            temperature=0.1,
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    def handle(self, message: str, context: Optional[dict] = None) -> dict:
        """
        Parse the user's intent and execute the appropriate write operation.

        Returns:
            {"response": str, "agent_used": str, "action_taken": str, "lead_id": int|None}
        """
        logger.info(f"[{AGENT_NAME}] Handling: {message[:80]}")

        intent = self._classify_intent(message)

        try:
            if intent == "CREATE":
                return self._handle_create(message, context)
            elif intent == "UPDATE":
                return self._handle_update(message, context)
            elif intent == "DELETE":
                return self._handle_delete(message, context)
            else:
                return {
                    "response": "I could not determine whether you want to create, update, or delete a lead. Please be more specific.",
                    "agent_used": AGENT_NAME,
                    "action_taken": "none",
                    "lead_id": None,
                }
        except Exception as e:
            logger.error(f"[{AGENT_NAME}] Error: {e}", exc_info=True)
            return {
                "response": f"An error occurred while executing the task: {str(e)}",
                "agent_used": AGENT_NAME,
                "action_taken": "error",
                "lead_id": None,
            }

    # ── Direct methods (called from /api/update-odoo-lead) ────────────────────

    def update_lead(self, lead_id: int, data: dict) -> bool:
        """Directly update a lead after validation. Used by /api/update-odoo-lead."""
        validation = self._validator.validate_update(lead_id, data)
        if not validation["valid"]:
            raise ValueError(f"Validation failed: {validation['errors']}")
        return self._odoo.update_lead(lead_id, validation["validated_data"])

    # ── Intent handlers ────────────────────────────────────────────────────────

    def _handle_create(self, message: str, context: Optional[dict]) -> dict:
        logger.info(f"[{AGENT_NAME}] Executing CREATE")
        data = self._extract_create_data(message, context)
        data = self._normalize_field_names(data)
        validation = self._validator.validate_create(data)

        if not validation["valid"]:
            return {
                "response": f"Cannot create lead — validation failed:\n" + "\n".join(f"• {e}" for e in validation["errors"]),
                "agent_used": AGENT_NAME,
                "action_taken": "validation_failed",
                "lead_id": None,
            }

        lead_id = self._odoo.create_lead(validation["validated_data"])
        logger.info(f"[{AGENT_NAME}] Lead created: id={lead_id}")
        name = data.get("name") or data.get("partner_name", "N/A")
        return {
            "response": (
                f"Lead created successfully!\n\n"
                f"• Lead ID: #{lead_id}\n"
                f"• Name: {name}\n"
                f"• Contact: {data.get('partner_name', 'N/A')}\n"
                f"• Email: {data.get('email_from', 'N/A')}"
            ),
            "agent_used": AGENT_NAME,
            "action_taken": "create_lead",
            "lead_id": lead_id,
        }

    def _handle_update(self, message: str, context: Optional[dict]) -> dict:
        logger.info(f"[{AGENT_NAME}] Executing UPDATE")
        lead_id = self._extract_lead_id(message, context)
        if not lead_id:
            return {
                "response": "Please specify which lead to update (e.g., 'update lead #5').",
                "agent_used": AGENT_NAME,
                "action_taken": "missing_lead_id",
                "lead_id": None,
            }

        data = self._extract_update_data(message)
        data = self._normalize_field_names(data)

        if not data:
            return {
                "response": f"Please specify what to update on lead #{lead_id} (e.g., priority, description, revenue).",
                "agent_used": AGENT_NAME,
                "action_taken": "missing_update_data",
                "lead_id": lead_id,
            }

        validation = self._validator.validate_update(lead_id, data)
        if not validation["valid"]:
            return {
                "response": f"Cannot update lead #{lead_id} — validation failed:\n" + "\n".join(f"• {e}" for e in validation["errors"]),
                "agent_used": AGENT_NAME,
                "action_taken": "validation_failed",
                "lead_id": lead_id,
            }

        self._odoo.update_lead(lead_id, validation["validated_data"])
        fields_updated = ", ".join(data.keys())
        logger.info(f"[{AGENT_NAME}] Lead #{lead_id} updated: {fields_updated}")
        return {
            "response": f"Lead #{lead_id} updated successfully.\nFields updated: {fields_updated}.",
            "agent_used": AGENT_NAME,
            "action_taken": "update_lead",
            "lead_id": lead_id,
        }

    def _handle_delete(self, message: str, context: Optional[dict]) -> dict:
        logger.info(f"[{AGENT_NAME}] Executing DELETE")
        lead_id = self._extract_lead_id(message, context)
        if not lead_id:
            return {
                "response": "Please specify which lead to delete (e.g., 'delete lead #7').",
                "agent_used": AGENT_NAME,
                "action_taken": "missing_lead_id",
                "lead_id": None,
            }

        # Verify the lead actually exists before attempting deletion
        try:
            self._odoo.read_lead(lead_id)
        except ValueError:
            logger.warning(f"[{AGENT_NAME}] Lead #{lead_id} not found — cannot delete")
            return {
                "response": (
                    f"Lead #{lead_id} was not found in Odoo.\n"
                    "It may have already been deleted or the ID does not exist."
                ),
                "agent_used": AGENT_NAME,
                "action_taken": "not_found",
                "lead_id": lead_id,
            }

        validation = self._validator.validate_delete(lead_id)
        if not validation["valid"]:
            return {
                "response": f"Cannot delete — validation failed: " + "; ".join(validation["errors"]),
                "agent_used": AGENT_NAME,
                "action_taken": "validation_failed",
                "lead_id": lead_id,
            }

        self._odoo.delete_lead(lead_id)
        logger.info(f"[{AGENT_NAME}] Lead #{lead_id} deleted")
        return {
            "response": f"Lead #{lead_id} has been permanently deleted from Odoo.",
            "agent_used": AGENT_NAME,
            "action_taken": "delete_lead",
            "lead_id": lead_id,
        }

    # ── Field normalization ───────────────────────────────────────────────────

    @staticmethod
    def _normalize_field_names(data: dict) -> dict:
        """
        Map natural-language / alias field names to canonical Odoo field names.
        e.g. {"email": "x@y.com"} → {"email_from": "x@y.com"}
        """
        normalized = {}
        for key, value in data.items():
            canonical = FIELD_ALIASES.get(key, key)
            normalized[canonical] = value
        return normalized

    # ── Extraction helpers ────────────────────────────────────────────────────

    def _classify_intent(self, message: str) -> str:
        """Classify the write intent from the message text."""
        msg = message.lower()
        if any(w in msg for w in ["create", "add", "new lead", "new contact", "register"]):
            return "CREATE"
        if any(w in msg for w in ["update", "edit", "change", "modify", "set ", "mark", "assign"]):
            return "UPDATE"
        if any(w in msg for w in ["delete", "remove", "archive", "unlink"]):
            return "DELETE"
        return "UNKNOWN"

    def _extract_lead_id(self, message: str, context: Optional[dict]) -> Optional[int]:
        if context and context.get("lead_id"):
            return int(context["lead_id"])
        patterns = [r"lead\s*#(\d+)", r"#(\d+)", r"\blead\s+(\d+)\b", r"\bid\s*[=:]?\s*(\d+)\b"]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def _extract_create_data(self, message: str, context: Optional[dict]) -> dict:
        """Use LLM to extract structured lead fields from free-form create request."""
        if context and isinstance(context, dict) and context.get("name"):
            return context

        prompt = f"""Extract CRM lead fields from this request. Return ONLY a valid Python dict.

Fields (use these exact key names):
- name: the opportunity/deal name (required) — if not given, compose from company name
- partner_name: the contact person's full name
- email_from: contact email address
- phone: contact phone number
- expected_revenue: numeric value only (no currency symbol)
- description: any notes or context

Request: "{message}"

Example: {{"name": "Tech Solutions Opportunity", "partner_name": "Ahmed Khan", "email_from": "ahmed@techsol.com"}}

Output only the dict, no explanation:"""

        try:
            response = self._llm.invoke([HumanMessage(content=prompt)])
            text = response.content.strip()
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                import ast
                return ast.literal_eval(match.group())
        except Exception as e:
            logger.error(f"[{AGENT_NAME}] LLM extraction failed: {e}")

        # Fallback: derive name from message
        return {"name": message[:100].strip()}

    def _extract_update_data(self, message: str) -> dict:
        """Use LLM to extract update fields from free-form update request."""
        prompt = f"""Extract the fields to update from this CRM lead update request.

Valid Odoo field names to use:
- name: opportunity/deal title
- partner_name: contact person name
- email_from: contact email address
- phone: contact phone number
- expected_revenue: numeric amount
- description: notes/description text
- priority: Odoo priority ("0"=normal, "1"=low, "2"=high, "3"=very high)

Request: "{message}"

Return ONLY a Python dict with the fields to change.
Example: {{"email_from": "new@company.com"}}
Example: {{"priority": "2", "description": "Updated notes"}}

Output only the dict, no explanation:"""

        try:
            response = self._llm.invoke([HumanMessage(content=prompt)])
            text = response.content.strip()
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                import ast
                return ast.literal_eval(match.group())
        except Exception as e:
            logger.error(f"[{AGENT_NAME}] LLM update extraction failed: {e}")

        return {}
