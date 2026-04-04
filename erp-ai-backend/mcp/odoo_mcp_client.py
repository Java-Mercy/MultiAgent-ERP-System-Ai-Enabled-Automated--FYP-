"""
mcp/odoo_mcp_client.py — Wrapper around Python's built-in xmlrpc.client for Odoo 17.

All Odoo XML-RPC calls are centralised here.
Agents NEVER import xmlrpc directly — they only call methods on this class.
"""

import xmlrpc.client
import logging
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)


class OdooMCPClient:
    """
    Provides a clean interface to Odoo via XML-RPC.

    Two Odoo XML-RPC endpoints are used:
      - /xmlrpc/2/common  → authenticate()
      - /xmlrpc/2/object  → execute_kw() for model operations
    """

    def __init__(self):
        self.url = settings.ODOO_URL
        self.db = settings.ODOO_DB
        self.username = settings.ODOO_USERNAME
        self.password = settings.ODOO_PASSWORD
        self._uid: Optional[int] = None

        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    # ── Authentication ────────────────────────────────────────────────────────

    def authenticate(self) -> int:
        """Authenticate with Odoo and cache the user ID."""
        try:
            uid = self._common.authenticate(self.db, self.username, self.password, {})
            if not uid:
                raise ConnectionError(
                    f"Odoo authentication failed for user '{self.username}' on db '{self.db}'"
                )
            self._uid = uid
            logger.info(f"[OdooMCPClient] Authenticated — uid={uid}")
            return uid
        except Exception as e:
            logger.error(f"[OdooMCPClient] authenticate() failed: {e}")
            raise

    def _get_uid(self) -> int:
        if self._uid is None:
            self.authenticate()
        return self._uid

    def _execute(self, model: str, method: str, *args, **kwargs) -> Any:
        """Low-level XML-RPC execute_kw call."""
        uid = self._get_uid()
        return self._models.execute_kw(
            self.db, uid, self.password, model, method, list(args), kwargs
        )

    # ── Lead / CRM Operations ─────────────────────────────────────────────────

    def search_leads(
        self,
        domain: Optional[list] = None,
        limit: int = 20,
        offset: int = 0,
        order: str = "id desc",
    ) -> list[dict]:
        """
        Search CRM leads.

        Args:
            domain: Odoo domain filter, e.g. [['priority', '=', '2']]
            limit:  Max records to return.
            offset: Pagination offset.
            order:  Sort order string.

        Returns:
            List of lead dicts with key fields.
        """
        if domain is None:
            domain = []
        try:
            ids = self._execute(
                "crm.lead", "search", domain,
                limit=limit, offset=offset, order=order
            )
            if not ids:
                return []
            return self.read_leads(ids)
        except Exception as e:
            logger.error(f"[OdooMCPClient] search_leads() failed: {e}")
            raise

    def read_lead(self, lead_id: int) -> dict:
        """Fetch a single lead by ID."""
        try:
            results = self.read_leads([lead_id])
            if not results:
                raise ValueError(f"Lead #{lead_id} not found in Odoo")
            return results[0]
        except Exception as e:
            logger.error(f"[OdooMCPClient] read_lead({lead_id}) failed: {e}")
            raise

    def read_leads(self, ids: list[int]) -> list[dict]:
        """Fetch multiple leads by ID list, including AI fields when available."""
        base_fields = [
            "id", "name", "partner_name", "email_from", "phone",
            "priority", "stage_id", "user_id", "team_id",
            "expected_revenue", "probability", "description",
            "date_deadline", "create_date", "write_date",
        ]
        try:
            ai_map = self._resolve_ai_field_map()
            fields = base_fields + list(ai_map.values())
        except RuntimeError:
            # crm_ai_assistant not installed — read base fields only
            fields = base_fields

        try:
            return self._execute("crm.lead", "read", ids, fields=fields)
        except Exception as e:
            logger.warning(f"[OdooMCPClient] read_leads failed, retrying with base fields only: {e}")
            return self._execute("crm.lead", "read", ids, fields=base_fields)

    def create_lead(self, data: dict) -> int:
        """
        Create a new CRM lead.

        Args:
            data: Dict of field values, e.g. {"name": "New Deal", "partner_name": "ACME"}

        Returns:
            New lead ID.
        """
        try:
            lead_id = self._execute("crm.lead", "create", data)
            logger.info(f"[OdooMCPClient] Created lead id={lead_id}")
            return lead_id
        except Exception as e:
            logger.error(f"[OdooMCPClient] create_lead() failed: {e}")
            raise

    def update_lead(self, lead_id: int, data: dict) -> bool:
        """
        Update an existing CRM lead.

        Args:
            lead_id: Odoo lead ID.
            data:    Dict of fields to update.

        Returns:
            True on success.
        """
        try:
            result = self._execute("crm.lead", "write", [lead_id], data)
            logger.info(f"[OdooMCPClient] Updated lead id={lead_id} fields={list(data.keys())}")
            return result
        except Exception as e:
            logger.error(f"[OdooMCPClient] update_lead({lead_id}) failed: {e}")
            raise

    def delete_lead(self, lead_id: int) -> bool:
        """
        Delete a CRM lead (unlink).

        Args:
            lead_id: Odoo lead ID.

        Returns:
            True on success.
        """
        try:
            result = self._execute("crm.lead", "unlink", [lead_id])
            logger.info(f"[OdooMCPClient] Deleted lead id={lead_id}")
            return result
        except Exception as e:
            logger.error(f"[OdooMCPClient] delete_lead({lead_id}) failed: {e}")
            raise

    def get_lead_fields(self) -> dict:
        """
        Introspect available fields on crm.lead model.

        Returns:
            Dict mapping field names to their metadata.
        """
        try:
            return self._execute(
                "crm.lead", "fields_get",
                attributes=["string", "type", "required", "readonly"]
            )
        except Exception as e:
            logger.error(f"[OdooMCPClient] get_lead_fields() failed: {e}")
            raise

    # ── AI Fields ─────────────────────────────────────────────────────────────

    # Resolved once per process — maps logical name → actual Odoo field name.
    _ai_field_map: Optional[dict] = None

    def _resolve_ai_field_map(self) -> dict:
        """
        Detect the actual field names used by the crm_ai_assistant module.

        The module may register fields as:
          - ai_summary / ai_priority_prediction / ai_email_draft   (native module)
          - x_ai_summary / x_ai_priority_prediction / x_ai_email_draft  (Studio)

        Returns a dict like:
            {
                "priority":   "ai_priority_prediction",   # or "x_ai_priority_prediction"
                "summary":    "ai_summary",
                "email_draft":"ai_email_draft",
            }
        Raises RuntimeError if none of the expected fields are found.
        """
        if OdooMCPClient._ai_field_map is not None:
            return OdooMCPClient._ai_field_map

        all_fields: dict = self._execute(
            "crm.lead", "fields_get",
            attributes=["type"],
        )

        candidates = {
            "priority": [
                "ai_priority_prediction",
                "x_ai_priority_prediction",
                "x_ai_priority",
                "ai_priority",
            ],
            "summary": [
                "ai_summary",
                "x_ai_summary",
            ],
            "email_draft": [
                "ai_email_draft",
                "x_ai_email_draft",
            ],
        }

        resolved: dict = {}
        for key, options in candidates.items():
            for candidate in options:
                if candidate in all_fields:
                    resolved[key] = candidate
                    logger.info(f"[OdooMCPClient] AI field '{key}' → '{candidate}'")
                    break

        if not resolved:
            raise RuntimeError(
                "crm_ai_assistant custom fields not found on crm.lead. "
                "Install the module in Odoo and re-run."
            )

        OdooMCPClient._ai_field_map = resolved
        return resolved

    def update_ai_fields(
        self,
        lead_id: int,
        priority: Optional[str] = None,
        summary: Optional[str] = None,
        email_draft: Optional[str] = None,
    ) -> dict:
        """
        Write AI-generated analysis results back to the crm_ai_assistant
        custom fields on the given lead.

        Args:
            lead_id:     Odoo CRM lead ID.
            priority:    Predicted priority — "High" | "Medium" | "Low"
                         (normalised to lowercase for the Selection field).
            summary:     AI-generated summary text.
            email_draft: AI-generated email draft text.

        Returns:
            {
                "success":        bool,
                "lead_id":        int,
                "fields_written": list[str],
                "field_map":      dict,   # logical → actual field name
            }

        Raises:
            RuntimeError if the module fields are not found.
            Exception on Odoo write failure.
        """
        field_map = self._resolve_ai_field_map()

        data: dict = {}

        if priority is not None and "priority" in field_map:
            # Selection values are stored lowercase: high / medium / low
            data[field_map["priority"]] = priority.strip().lower()

        if summary is not None and "summary" in field_map:
            data[field_map["summary"]] = summary.strip()

        if email_draft is not None and "email_draft" in field_map:
            data[field_map["email_draft"]] = email_draft.strip()

        if not data:
            logger.warning(f"[OdooMCPClient] update_ai_fields: nothing to write for lead #{lead_id}")
            return {
                "success": False,
                "lead_id": lead_id,
                "fields_written": [],
                "field_map": field_map,
            }

        result = self._execute("crm.lead", "write", [lead_id], data)
        logger.info(
            f"[OdooMCPClient] update_ai_fields: lead #{lead_id} "
            f"written fields={list(data.keys())} result={result}"
        )
        return {
            "success": bool(result),
            "lead_id": lead_id,
            "fields_written": list(data.keys()),
            "field_map": field_map,
        }

    def search_leads_by_name(self, name: str, limit: int = 10) -> list[dict]:
        """Convenience: search leads whose name contains the given string."""
        return self.search_leads(domain=[["name", "ilike", name]], limit=limit)

    def get_lead_count(self, domain: Optional[list] = None) -> int:
        """Return count of leads matching domain."""
        if domain is None:
            domain = []
        try:
            return self._execute("crm.lead", "search_count", domain)
        except Exception as e:
            logger.error(f"[OdooMCPClient] get_lead_count() failed: {e}")
            raise
