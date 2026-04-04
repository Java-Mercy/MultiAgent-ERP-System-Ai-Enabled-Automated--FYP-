"""
agents/action_validator.py — Agent 4: Action Validator

Validates data schema and permissions before any write operation is executed.
Called by TaskExecutorAgent before every create/update/delete.

Returns: {"valid": bool, "errors": list[str], "validated_data": dict}
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME = "ActionValidatorAgent"

# Required fields for creating a new lead
CREATE_REQUIRED_FIELDS = ["name"]

# Fields that must be strings if present
STRING_FIELDS = [
    "name", "partner_name", "email_from", "phone",
    "description", "x_ai_priority", "x_ai_summary", "x_ai_email_draft",
]

# Fields that must be numeric if present
NUMERIC_FIELDS = ["expected_revenue", "probability"]

# Allowed Odoo priority values
VALID_PRIORITY_VALUES = {"0", "1", "2", "3"}  # Odoo: normal / low / high / very high

# Allowed AI priority labels (our custom field)
VALID_AI_PRIORITY_LABELS = {"High", "Medium", "Low"}


class ActionValidatorAgent:
    """
    Validates CRM lead data before it reaches Odoo.

    Checks:
      - Required fields are present for create operations
      - Data types match expected types
      - Email format is valid when provided
      - Probability is within [0, 100]
      - No obviously empty / blank required fields
    """

    def validate_create(self, data: dict) -> dict:
        """Validate a lead creation payload."""
        logger.info(f"[{AGENT_NAME}] Validating CREATE payload: {list(data.keys())}")
        errors = []
        validated = dict(data)

        # Required fields
        for field in CREATE_REQUIRED_FIELDS:
            if not data.get(field, "").strip():
                errors.append(f"Required field '{field}' is missing or empty.")

        errors.extend(self._check_types(data))
        errors.extend(self._check_email(data))
        errors.extend(self._check_probability(data))
        errors.extend(self._check_ai_priority(data))

        valid = len(errors) == 0
        result = {"valid": valid, "errors": errors, "validated_data": validated}
        logger.info(f"[{AGENT_NAME}] CREATE validation result: valid={valid}, errors={errors}")
        return result

    def validate_update(self, lead_id: int, data: dict) -> dict:
        """Validate a lead update payload."""
        logger.info(f"[{AGENT_NAME}] Validating UPDATE lead_id={lead_id}: {list(data.keys())}")
        errors = []
        validated = dict(data)

        if not lead_id or lead_id <= 0:
            errors.append("lead_id must be a positive integer.")

        if not data:
            errors.append("Update payload is empty — nothing to update.")

        errors.extend(self._check_types(data))
        errors.extend(self._check_email(data))
        errors.extend(self._check_probability(data))
        errors.extend(self._check_ai_priority(data))

        valid = len(errors) == 0
        result = {"valid": valid, "errors": errors, "validated_data": validated}
        logger.info(f"[{AGENT_NAME}] UPDATE validation result: valid={valid}, errors={errors}")
        return result

    def validate_delete(self, lead_id: int) -> dict:
        """Validate a lead deletion request."""
        logger.info(f"[{AGENT_NAME}] Validating DELETE lead_id={lead_id}")
        errors = []

        if not lead_id or lead_id <= 0:
            errors.append("lead_id must be a positive integer for deletion.")

        valid = len(errors) == 0
        result = {"valid": valid, "errors": errors, "validated_data": {"lead_id": lead_id}}
        logger.info(f"[{AGENT_NAME}] DELETE validation result: valid={valid}, errors={errors}")
        return result

    # ── Private helpers ────────────────────────────────────────────────────────

    def _check_types(self, data: dict) -> list[str]:
        errors = []
        for field in STRING_FIELDS:
            if field in data and not isinstance(data[field], str):
                errors.append(f"Field '{field}' must be a string, got {type(data[field]).__name__}.")
        for field in NUMERIC_FIELDS:
            if field in data:
                val = data[field]
                if not isinstance(val, (int, float)):
                    errors.append(f"Field '{field}' must be numeric, got {type(val).__name__}.")
        return errors

    def _check_email(self, data: dict) -> list[str]:
        errors = []
        email = data.get("email_from", "")
        if email:
            pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
            if not re.match(pattern, email):
                errors.append(f"'email_from' value '{email}' is not a valid email address.")
        return errors

    def _check_probability(self, data: dict) -> list[str]:
        errors = []
        if "probability" in data:
            val = data["probability"]
            if isinstance(val, (int, float)) and not (0 <= val <= 100):
                errors.append(f"'probability' must be between 0 and 100, got {val}.")
        return errors

    def _check_ai_priority(self, data: dict) -> list[str]:
        errors = []
        if "x_ai_priority" in data:
            val = data["x_ai_priority"]
            if val not in VALID_AI_PRIORITY_LABELS:
                errors.append(
                    f"'x_ai_priority' must be one of {VALID_AI_PRIORITY_LABELS}, got '{val}'."
                )
        return errors
