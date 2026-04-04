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
from typing import Optional

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings
from agents.data_retriever import DataRetrieverAgent
from agents.task_executor import TaskExecutorAgent
from agents.communication_agent import CommunicationAgent
from rag.pinecone_store import PineconeStore

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
      2. Instantiate and call the appropriate specialist agent.
      3. Return the combined response to the caller.
    """

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

    async def handle(self, message: str, session_id: str = "default", context: Optional[dict] = None) -> dict:
        """
        Route a user message to the appropriate specialist agent.

        Args:
            message:    The user's natural language message.
            session_id: Session identifier for multi-turn tracking.
            context:    Optional pre-parsed context (e.g. {"lead_id": 5}).

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

        intent = self._classify_intent(message)
        logger.info(f"[{AGENT_NAME}] Classified intent: {intent} → {INTENT_AGENT_MAP.get(intent, 'Unknown')}")

        try:
            if intent == "QUERY":
                result = self._get_data_retriever().handle(message, context)

            elif intent == "ACTION":
                result = self._get_task_executor().handle(message, context)

            elif intent in ("ANALYSIS", "COMMUNICATION"):
                result = self._get_communication_agent().handle(message, context)

            else:
                result = self._handle_unknown(message)

            # Ensure intent is always included in the response
            result["intent"] = intent
            result.setdefault("action_taken", None)
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
            response = self._llm.invoke([
                SystemMessage(content=system),
                HumanMessage(content=message),
            ])
            intent = response.content.strip().upper()
            if intent in INTENT_AGENT_MAP:
                return intent
            logger.warning(f"[{AGENT_NAME}] LLM returned unexpected intent '{intent}', using rule-based fallback.")
        except Exception as e:
            logger.error(f"[{AGENT_NAME}] LLM classification failed: {e}. Using rule-based fallback.")

        return self._rule_based_classify(message)

    @staticmethod
    def _rule_based_classify(message: str) -> str:
        """Fallback keyword-based intent classification."""
        msg = message.lower()

        query_kw = ["show", "list", "get", "search", "find", "display", "view", "filter", "fetch", "all leads"]
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
