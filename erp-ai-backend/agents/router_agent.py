"""
agents/router_agent.py — Agent 1: Router Agent

Receives every user message, classifies intent using the LLM,
and routes to the correct specialist agent.

Intent classes:
  QUERY         → DataRetrieverAgent  (read, search, list, show)
  ACTION        → TaskExecutorAgent   (create, update, delete)
  ANALYSIS      → CommunicationAgent  (analyze, prioritize, assess)
  COMMUNICATION → CommunicationAgent  (email, summary, draft)
"""

import logging
import re
from typing import Optional

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings
from agents.data_retriever import DataRetrieverAgent
from agents.task_executor import TaskExecutorAgent
from agents.communication_agent import CommunicationAgent
from agents.action_validator import RBAC_DENY_MESSAGE
from rag.pinecone_store import PineconeStore
from utils.llm_retry import invoke_groq, GroqUnavailableError

logger = logging.getLogger(__name__)
AGENT_NAME = "RouterAgent"

# Intent → agent label mapping (for logging)
INTENT_AGENT_MAP = {
    "QUERY": "DataRetrieverAgent",
    "ACTION": "TaskExecutorAgent",
    "ANALYSIS": "CommunicationAgent",
    "COMMUNICATION": "CommunicationAgent",
}


class RouterAgent:
    """
    Central dispatcher for the multi-agent ERP system.

    Responsibilities:
      1. Classify the user's intent via LLM.
      2. Resolve ambiguous references using session history (e.g. "the first one").
      3. Instantiate and call the appropriate specialist agent.
      4. Return the combined response to the caller.
    """

    # In-memory session store: session_id → list of {role, content, data}
    # Keeps last 20 entries (10 exchanges) per session.
    _session_store: dict = {}

    # Pending clarification: session_id → {"partial": str} — follow-up is merged into the command.
    _clarification_store: dict = {}

    def __init__(self):
        self._llm = ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            temperature=0.0,  # Deterministic routing
        )
        # Shared PineconeStore so embeddings load only once
        self._pinecone = PineconeStore()

        # Lazy-initialised specialist agents
        self._data_retriever: Optional[DataRetrieverAgent] = None
        self._task_executor: Optional[TaskExecutorAgent] = None
        self._communication: Optional[CommunicationAgent] = None

    # ── Main entry point ──────────────────────────────────────────────────────

    async def handle(
        self,
        message: str,
        session_id: str = "default",
        context: Optional[dict] = None,
        role: str = "admin",
    ) -> dict:
        """
        Route a user message to the appropriate specialist agent.

        Args:
            message:    The user's natural language message.
            session_id: Session identifier for multi-turn tracking.
            context:    Optional pre-parsed context (e.g. {"lead_id": 5}).
            role:       "admin" (full access) or "user" (read + summaries only).

        Returns:
            {
                "response": str,
                "agent_used": str,
                "intent": str,
                "action_taken": str | None,
                ...additional agent-specific fields
            }
        """
        logger.info(f"[{AGENT_NAME}] session={session_id} | message={message[:80]}")

        raw_user_message = message

        # Continue a clarification dialog: merge prior partial command with this reply
        pending = RouterAgent._clarification_store.pop(session_id, None)
        if pending and pending.get("partial"):
            message = f"{pending['partial']} — {message}".strip()
            logger.info(f"[{AGENT_NAME}] Merged clarification follow-up → {message[:100]}")

        # Load conversation history for this session
        history = RouterAgent._session_store.get(session_id, [])

        # Resolve ambiguous references (e.g. "the first one", "tell me more about it")
        # Only use if caller didn't provide explicit context
        resolved_context = context if context else self._resolve_references(message, history)

        intent = self._classify_intent(message)
        logger.info(f"[{AGENT_NAME}] Classified intent: {intent} → {INTENT_AGENT_MAP.get(intent, 'Unknown')}")

        rbac_block = self._router_rbac_block(role, intent, message)
        if rbac_block is not None:
            result = rbac_block
            result["intent"] = intent
            result.setdefault("action_taken", "unauthorized")
            new_history = list(history)
            new_history.append({"role": "user", "content": raw_user_message})
            new_history.append({
                "role": "assistant",
                "content": result.get("response", ""),
                "data": result.get("data"),
            })
            RouterAgent._session_store[session_id] = new_history[-20:]
            return result

        clarify = self._maybe_request_clarification(intent, message, resolved_context, session_id)
        if clarify is not None:
            result = clarify
            result["intent"] = intent
            result.setdefault("action_taken", "awaiting_clarification")
            new_history = list(history)
            new_history.append({"role": "user", "content": raw_user_message})
            new_history.append({
                "role": "assistant",
                "content": result.get("response", ""),
                "data": result.get("data"),
            })
            RouterAgent._session_store[session_id] = new_history[-20:]
            return result

        try:
            if intent == "QUERY":
                result = self._get_data_retriever().handle(message, resolved_context)

            elif intent == "ACTION":
                result = self._get_task_executor().handle(message, resolved_context, role=role)

            elif intent in ("ANALYSIS", "COMMUNICATION"):
                result = self._get_communication_agent().handle(message, resolved_context)

            else:
                result = self._handle_unknown(message)

            # Ensure intent is always included in the response
            result["intent"] = intent
            result.setdefault("action_taken", None)

            # Persist exchange to session history
            new_history = list(history)
            new_history.append({"role": "user", "content": raw_user_message})
            new_history.append({
                "role": "assistant",
                "content": result.get("response", ""),
                "data": result.get("data"),          # lead list/dict for reference resolution
            })
            RouterAgent._session_store[session_id] = new_history[-20:]  # cap at 10 exchanges

            return result

        except Exception as e:
            logger.error(f"[{AGENT_NAME}] Routing error: {e}", exc_info=True)
            return {
                "response": f"An unexpected error occurred in the routing layer: {str(e)}",
                "agent_used": AGENT_NAME,
                "intent": intent,
                "action_taken": "error",
            }

    # ── Intent classification ─────────────────────────────────────────────────

    def _classify_intent(self, message: str) -> str:
        """
        Use the LLM to classify the user's message into one of four intent categories.
        Falls back to rule-based classification if LLM fails.
        """
        system = (
            "You are an intent classifier for a CRM system. "
            "Classify the user message into EXACTLY ONE of these categories:\n\n"
            "  QUERY         - Reading, searching, listing, or filtering leads\n"
            "  ACTION        - Creating, updating, or deleting leads\n"
            "  ANALYSIS      - Analyzing a lead, assigning priority, assessing opportunity\n"
            "  COMMUNICATION - Drafting emails, writing summaries, generating follow-ups\n\n"
            "Respond with ONLY the category name. No explanation."
        )
        try:
            response = invoke_groq(self._llm, [
                SystemMessage(content=system),
                HumanMessage(content=message),
            ])
            intent = response.content.strip().upper()
            if intent in INTENT_AGENT_MAP:
                return intent
            logger.warning(f"[{AGENT_NAME}] LLM returned unexpected intent '{intent}', using rule-based fallback.")
        except GroqUnavailableError:
            logger.error(f"[{AGENT_NAME}] Groq unavailable during intent classification — rule-based fallback.")
        except Exception as e:
            logger.error(f"[{AGENT_NAME}] LLM classification failed: {e}. Using rule-based fallback.")

        return self._rule_based_classify(message)

    @staticmethod
    def _rule_based_classify(message: str) -> str:
        """Fallback keyword-based intent classification."""
        msg = message.lower()

        query_kw = ["show", "list", "get", "search", "find", "display", "view", "filter", "fetch", "all leads", "tell me more", "more about", "more details"]
        action_kw = ["create", "add", "new lead", "update", "edit", "change", "delete", "remove"]
        analysis_kw = ["analyze", "analyse", "priority", "assess", "evaluate", "score", "rank"]
        comm_kw = ["email", "draft", "write", "summary", "summarize", "follow-up", "generate", "compose"]

        if any(k in msg for k in action_kw):
            return "ACTION"
        if any(k in msg for k in comm_kw):
            return "COMMUNICATION"
        if any(k in msg for k in analysis_kw):
            return "ANALYSIS"
        if any(k in msg for k in query_kw):
            return "QUERY"

        return "QUERY"  # Safe default

    # ── Session reference resolution ──────────────────────────────────────────

    def _resolve_references(self, message: str, history: list) -> Optional[dict]:
        """
        Detect references to previously retrieved leads and resolve them to a
        concrete lead_id using session history.

        Examples handled:
          "Tell me more about the first one"  → {"lead_id": <first lead's id>}
          "More details on the second lead"   → {"lead_id": <second lead's id>}
          "What about the last one?"          → {"lead_id": <last lead's id>}
        """
        if not history:
            return None

        msg = message.lower()

        # Don't interfere if the message already contains an explicit lead ID
        has_explicit_id = bool(re.search(r"lead\s*#\s*\d+|#\d+|\bid\s*\d+|\blead\s+\d+", msg))
        if has_explicit_id:
            return None

        # Patterns that suggest a reference to a previously shown lead
        reference_triggers = [
            "first one", "first lead", "the first",
            "second one", "second lead", "the second",
            "third one", "third lead", "the third",
            "last one", "last lead", "the last",
            "tell me more", "more about",
            "more details", "more info",
            "that lead", "this lead",
            "for them", "for him", "for her", "for it",
            "that one", "this one", "them", "it"
        ]

        if not any(pat in msg for pat in reference_triggers):
            return None

        # Walk backward through history to find the last response containing lead data
        for entry in reversed(history):
            if entry.get("role") != "assistant":
                continue
            data = entry.get("data")
            if not data:
                continue

            leads = data if isinstance(data, list) else ([data] if isinstance(data, dict) and data.get("id") else [])
            if not leads:
                continue

            # Determine which lead to reference based on ordinal keywords
            if "second" in msg and len(leads) > 1:
                target = leads[1]
            elif "third" in msg and len(leads) > 2:
                target = leads[2]
            elif "last" in msg:
                target = leads[-1]
            else:
                target = leads[0]  # Default: first

            lead_id = target.get("id") if isinstance(target, dict) else None
            if lead_id:
                logger.info(f"[{AGENT_NAME}] Session reference resolved to lead #{lead_id} from history")
                return {"lead_id": lead_id}

        return None

    # ── RBAC (SRS 3.2.7) ─────────────────────────────────────────────────────

    def _router_rbac_block(self, role: str, intent: str, message: str) -> Optional[dict]:
        """Returns a response dict if this role may not perform the classified intent."""
        r = (role or "admin").strip().lower()
        if r == "admin":
            return None
        if r != "user":
            r = "user"

        if intent == "QUERY":
            return None
        if intent == "ACTION":
            return self._rbac_denied_dict()
        if intent == "ANALYSIS":
            return self._rbac_denied_dict()
        if intent == "COMMUNICATION":
            if self._user_summary_allowed(message):
                return None
            return self._rbac_denied_dict()
        return self._rbac_denied_dict()

    @staticmethod
    def _rbac_denied_dict() -> dict:
        return {
            "response": RBAC_DENY_MESSAGE,
            "agent_used": "ActionValidatorAgent",
            "action_taken": "unauthorized",
        }

    @staticmethod
    def _user_summary_allowed(message: str) -> bool:
        m = message.lower()
        return any(
            k in m
            for k in ["summarize", "summarise", "summary", "overview", "brief", "describe"]
        )

    # ── Clarification dialogs (SRS 3.2.6) ─────────────────────────────────────

    def _maybe_request_clarification(
        self,
        intent: str,
        message: str,
        context: Optional[dict],
        session_id: str,
    ) -> Optional[dict]:
        """Ask a follow-up when the command is too incomplete to execute safely."""
        sub = self._task_write_sub_intent(message)

        if intent == "ACTION":
            if sub == "CREATE" and self._needs_create_clarification(message, context):
                RouterAgent._clarification_store[session_id] = {"partial": message.strip()}
                return {
                    "response": "What's the lead's name and company?",
                    "agent_used": AGENT_NAME,
                    "action_taken": None,
                }
            if sub == "UPDATE" and not self._lead_id_resolved(message, context):
                RouterAgent._clarification_store[session_id] = {"partial": message.strip()}
                return {
                    "response": "Which lead? Please provide the lead ID.",
                    "agent_used": AGENT_NAME,
                    "action_taken": None,
                }
            if sub == "DELETE" and self._needs_delete_clarification(message, context):
                RouterAgent._clarification_store[session_id] = {"partial": message.strip()}
                return {
                    "response": "What would you like to delete? Specify type and ID.",
                    "agent_used": AGENT_NAME,
                    "action_taken": None,
                }

        if intent == "COMMUNICATION" and self._needs_email_clarification(message):
            RouterAgent._clarification_store[session_id] = {"partial": message.strip()}
            return {
                "response": "Draft a new email or send existing? For which lead?",
                "agent_used": AGENT_NAME,
                "action_taken": None,
            }

        return None

    @staticmethod
    def _task_write_sub_intent(message: str) -> str:
        msg = message.lower()
        if any(w in msg for w in ["create", "add", "new lead", "new contact", "register"]):
            return "CREATE"
        if any(w in msg for w in ["update", "edit", "change", "modify", "set ", "mark", "assign"]):
            return "UPDATE"
        if any(w in msg for w in ["delete", "remove", "archive", "unlink"]):
            return "DELETE"
        return "UNKNOWN"

    @staticmethod
    def _lead_id_resolved(message: str, context: Optional[dict]) -> bool:
        if context and context.get("lead_id"):
            return True
        if bool(
            re.search(r"lead\s*#\s*\d+|#\d+|\blead\s+\d+\b|\bid\s*[=:]?\s*\d+", message.lower())
        ):
            return True
        # Follow-up after clarification: "… — 12" or "… — lead #4"
        if " — " in message:
            tail = message.split(" — ", 1)[-1].strip()
            if re.search(r"^\d+$", tail) or re.search(r"lead\s*#?\s*\d+|#\d+", tail.lower()):
                return True
        return False

    @staticmethod
    def _needs_create_clarification(message: str, context: Optional[dict]) -> bool:
        if context and (context.get("name") or context.get("partner_name")):
            return False
        # Merged follow-up already appended details after em dash
        if " — " in message:
            tail = message.split(" — ", 1)[-1].strip()
            if len(tail) >= 3:
                return False
        m = message.lower().strip()
        if not any(x in m for x in ["create", "add", "new lead", "new contact"]):
            return False
        if re.search(r"\bfor\s+[A-Za-z0-9][A-Za-z0-9 &.'\-,]{1,}", m):
            return False
        if re.search(r"\bnamed?\s+[A-Za-z0-9]", m):
            return False
        if re.search(r"\bcalled\s+[A-Za-z0-9]", m):
            return False
        if "@" in message:
            return False
        return True

    @staticmethod
    def _needs_delete_clarification(message: str, context: Optional[dict]) -> bool:
        if context and context.get("lead_id"):
            return False
        if " — " in message:
            tail = message.split(" — ", 1)[-1].strip()
            if RouterAgent._lead_id_resolved(tail, context):
                return False
        m = message.lower()
        if not any(w in m for w in ["delete", "remove", "unlink"]):
            return False
        if RouterAgent._lead_id_resolved(message, context):
            return False
        return True

    @staticmethod
    def _needs_email_clarification(message: str) -> bool:
        if " — " in message:
            tail = message.split(" — ", 1)[-1].strip().lower()
            if len(tail) >= 3:
                return False
        m = message.strip().lower()
        if "email" not in m and "e-mail" not in m:
            return False
        if re.search(r"lead\s*#\s*\d+|#\d+|\blead\s+\d+\b", m):
            return False
        if any(
            x in m
            for x in ["draft", "send", "compose", "write", "follow-up", "follow up", "summarize", "summarise"]
        ):
            return False
        if len(m.split()) <= 3:
            return True
        return False

    # ── Unknown intent ────────────────────────────────────────────────────────

    def _handle_unknown(self, message: str) -> dict:
        logger.warning(f"[{AGENT_NAME}] Could not classify intent for: {message[:80]}")
        return {
            "response": (
                "I'm not sure how to handle that request. Here's what I can do:\n\n"
                "• **Show leads** — 'Show all leads' / 'Get lead #5'\n"
                "• **Create leads** — 'Create a lead for ACME Corp'\n"
                "• **Update leads** — 'Update lead #3, set priority to High'\n"
                "• **Delete leads** — 'Delete lead #7'\n"
                "• **Draft emails** — 'Draft a follow-up email for lead #2'\n"
                "• **Analyze leads** — 'Analyze lead #4'\n"
                "• **Summarize** — 'Summarize lead #1'"
            ),
            "agent_used": AGENT_NAME,
            "action_taken": "help_displayed",
        }

    # ── Lazy agent getters ────────────────────────────────────────────────────

    def _get_data_retriever(self) -> DataRetrieverAgent:
        if self._data_retriever is None:
            self._data_retriever = DataRetrieverAgent()
        return self._data_retriever

    def _get_task_executor(self) -> TaskExecutorAgent:
        if self._task_executor is None:
            self._task_executor = TaskExecutorAgent()
        return self._task_executor

    def _get_communication_agent(self) -> CommunicationAgent:
        if self._communication is None:
            self._communication = CommunicationAgent(pinecone_store=self._pinecone)
        return self._communication
