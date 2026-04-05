"""
agents/communication_agent.py — Agent 5: Communication Agent

Drafts emails, generates summaries, and produces lead analyses.

MANDATORY RAG USAGE:
  This agent NEVER generates emails without first querying Pinecone for
  relevant policy/template context. See _retrieve_policy_context().
"""

import logging
from typing import Optional

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings
from mcp.odoo_mcp_client import OdooMCPClient
from rag.pinecone_store import PineconeStore
from utils.llm_retry import invoke_groq, GroqUnavailableError

logger = logging.getLogger(__name__)
AGENT_NAME = "CommunicationAgent"

RAG_FALLBACK_NOTE = (
    "\n\n_(Note: The knowledge base was unavailable, so this reply was generated without "
    "retrieved company policy context.)_"
)


class CommunicationAgent:
    """
    Generates AI-powered CRM communications grounded in company policy via RAG.

    Workflow for every email/summary request:
      1. Fetch lead data from Odoo (if lead_id provided).
      2. Query Pinecone to retrieve relevant policy/template chunks.
      3. Pass lead data + retrieved context to LLM.
      4. Return the grounded response.
    """

    def __init__(self, pinecone_store: Optional[PineconeStore] = None):
        self._odoo = OdooMCPClient()
        self._pinecone = pinecone_store or PineconeStore()
        self._llm = ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            temperature=0.4,
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    def handle(self, message: str, context: Optional[dict] = None) -> dict:
        """
        Handle communication requests: email drafts, summaries, analysis.

        Returns:
            {
                "response": str,
                "agent_used": str,
                "priority": str | None,
                "summary": str | None,
                "email_draft": str | None,
                "rag_context_used": bool,
            }
        """
        logger.info(f"[{AGENT_NAME}] Handling: {message[:80]}")

        try:
            lead_id = self._extract_lead_id(message, context)
            lead_data = None

            if lead_id:
                try:
                    lead_data = self._odoo.read_lead(lead_id)
                    logger.info(f"[{AGENT_NAME}] Fetched lead #{lead_id} for communication")
                except Exception as e:
                    logger.warning(f"[{AGENT_NAME}] Could not fetch lead #{lead_id}: {e}")

            # Determine task type
            if self._is_analysis_request(message):
                return self._analyze_lead(message, lead_data, context)
            elif self._is_summary_request(message):
                return self._summarize_lead(message, lead_data)
            else:
                return self._draft_email(message, lead_data)

        except Exception as e:
            logger.error(f"[{AGENT_NAME}] Error: {e}", exc_info=True)
            return {
                "response": f"Error in CommunicationAgent: {str(e)}",
                "agent_used": AGENT_NAME,
                "priority": None,
                "summary": None,
                "email_draft": None,
                "rag_context_used": False,
            }

    # ── Task handlers ─────────────────────────────────────────────────────────

    def _draft_email(self, message: str, lead: Optional[dict]) -> dict:
        """Draft a professional email grounded in retrieved policy context."""
        logger.info(f"[{AGENT_NAME}] Drafting email …")

        # Build RAG query from lead context
        rag_query = self._build_rag_query(message, lead, task="email")
        policy_chunks, rag_degraded = self._retrieve_policy_context(rag_query)
        context_text = self._format_policy_context(policy_chunks)

        lead_text = self._format_lead_for_prompt(lead) if lead else "No lead data available."

        system_prompt = (
            "You are a professional CRM email writer. "
            "You MUST use the provided company email policies and templates to guide your writing. "
            "Write emails that are concise, personalized, and action-oriented. "
            "Include a Subject line and sign off professionally."
        )

        user_prompt = (
            f"Task: {message}\n\n"
            f"Lead Information:\n{lead_text}\n\n"
            f"Company Email Policy & Templates (retrieved from knowledge base):\n{context_text}\n\n"
            "Write a professional email following the retrieved policy guidelines."
        )

        email_draft = self._invoke_llm(system_prompt, user_prompt)
        if rag_degraded:
            email_draft = (email_draft or "").rstrip() + RAG_FALLBACK_NOTE
        logger.info(f"[{AGENT_NAME}] Email draft generated (RAG chunks used: {len(policy_chunks)})")

        # Use a short intro as the bubble text; full email goes into email_draft field
        # (prevents duplicate rendering in the frontend)
        lead_name = lead.get("name", "the lead") if lead else "the lead"
        intro = f"Here's a professional follow-up email for {lead_name}, based on company email policy:"

        return {
            "response": intro,
            "agent_used": AGENT_NAME,
            "priority": None,
            "summary": None,
            "email_draft": email_draft,
            "rag_context_used": len(policy_chunks) > 0,
        }

    def _summarize_lead(self, message: str, lead: Optional[dict]) -> dict:
        """Summarize a lead's status and recommended next action."""
        logger.info(f"[{AGENT_NAME}] Summarizing lead …")

        rag_query = self._build_rag_query(message, lead, task="summary")
        policy_chunks, rag_degraded = self._retrieve_policy_context(rag_query)
        context_text = self._format_policy_context(policy_chunks)

        lead_text = self._format_lead_for_prompt(lead) if lead else "No lead data available."

        system_prompt = (
            "You are a CRM analyst. Summarize the lead's current status, key details, "
            "and recommended next action. Keep the summary under 5 sentences. "
            "Use the company policy context to inform your recommendation."
        )

        user_prompt = (
            f"Lead Information:\n{lead_text}\n\n"
            f"CRM Policy Context:\n{context_text}\n\n"
            f"User request: {message}"
        )

        summary = self._invoke_llm(system_prompt, user_prompt)
        if rag_degraded:
            summary = (summary or "").rstrip() + RAG_FALLBACK_NOTE

        return {
            "response": summary,
            "agent_used": AGENT_NAME,
            "priority": None,
            "summary": summary,
            "email_draft": None,
            "rag_context_used": len(policy_chunks) > 0,
        }

    def _analyze_lead(self, message: str, lead: Optional[dict], context: Optional[dict]) -> dict:
        """
        Full lead analysis: assigns priority, writes summary, and drafts an email.
        Used by the /api/analyze-lead endpoint.
        """
        logger.info(f"[{AGENT_NAME}] Full lead analysis …")
        notes = (context or {}).get("notes", "")

        # Query Pinecone for both scoring policy and email templates
        scoring_chunks, deg1 = self._retrieve_policy_context("lead scoring priority assignment rules budget timeline")
        email_chunks, deg2 = self._retrieve_policy_context("follow-up email professional first contact template")
        rag_degraded = deg1 or deg2
        all_chunks = scoring_chunks + email_chunks
        context_text = self._format_policy_context(all_chunks)

        lead_text = self._format_lead_for_prompt(lead) if lead else "No lead data available."

        system_prompt = (
            "You are an intelligent CRM AI assistant. Based on the lead data and company policies, "
            "produce a structured analysis. Follow the scoring policy exactly."
        )

        user_prompt = (
            f"Lead Information:\n{lead_text}\n"
            f"Additional Notes: {notes or 'None'}\n\n"
            f"Company CRM Policies (retrieved from knowledge base):\n{context_text}\n\n"
            "Provide your analysis in this EXACT format:\n\n"
            "PRIORITY: [High/Medium/Low]\n\n"
            "SUMMARY:\n[2-3 sentence summary of the lead and recommended action]\n\n"
            "EMAIL DRAFT:\n[Complete professional email with Subject line]"
        )

        raw_response = self._invoke_llm(system_prompt, user_prompt)

        # Parse structured response
        priority = self._parse_section(raw_response, "PRIORITY")
        summary = self._parse_section(raw_response, "SUMMARY")
        email_draft = self._parse_section(raw_response, "EMAIL DRAFT")

        # Normalise priority
        if priority:
            priority = priority.strip().split()[0].capitalize()
            if priority not in {"High", "Medium", "Low"}:
                priority = "Medium"
        else:
            priority = "Medium"

        logger.info(f"[{AGENT_NAME}] Analysis complete — priority={priority}, rag_chunks={len(all_chunks)}")

        # Build a clean response for the chat bubble (not the raw LLM output)
        clean_response = (
            f"Lead analysis complete.\n\n"
            f"Priority: {priority}\n\n"
            f"{summary or 'See email draft for full details.'}"
        )
        summary_out = summary or raw_response[:300]
        if rag_degraded:
            clean_response = clean_response.rstrip() + RAG_FALLBACK_NOTE
            email_draft = (email_draft or "").rstrip() + RAG_FALLBACK_NOTE
            summary_out = (summary_out or "").rstrip() + RAG_FALLBACK_NOTE

        return {
            "response": clean_response,
            "agent_used": AGENT_NAME,
            "priority": priority,
            "summary": summary_out,
            "email_draft": email_draft or "",
            "rag_context_used": len(all_chunks) > 0,
        }

    # ── RAG ───────────────────────────────────────────────────────────────────

    def _retrieve_policy_context(self, query: str) -> tuple[list[str], bool]:
        """
        Query Pinecone for relevant policy/template chunks.

        Returns (chunks, rag_degraded). rag_degraded True when Pinecone/embeddings failed
        or are unavailable — caller should generate without RAG and may add a user note.
        """
        chunks, degraded = self._pinecone.query_chunks(query, top_k=3)
        if degraded:
            logger.warning(f"[{AGENT_NAME}] RAG degraded — proceeding without retrieved policy context.")
        else:
            logger.info(f"[{AGENT_NAME}] Retrieved {len(chunks)} policy chunks from Pinecone.")
        return chunks, degraded

    def _build_rag_query(self, message: str, lead: Optional[dict], task: str) -> str:
        """Build a descriptive RAG query combining the task type and lead context."""
        parts = []
        if task == "email":
            parts.append("professional email template follow-up first contact")
        elif task == "summary":
            parts.append("lead summary analysis CRM best practices")

        if lead:
            if lead.get("priority") == "2":
                parts.append("high priority urgent lead")
            revenue = lead.get("expected_revenue", 0)
            if revenue and float(revenue) > 5000:
                parts.append("high value deal")
            elif revenue and float(revenue) < 1000:
                parts.append("low budget lead")

        parts.append(message[:100])
        return " ".join(parts)

    @staticmethod
    def _format_policy_context(chunks: list[str]) -> str:
        if not chunks:
            return "No policy context retrieved."
        return "\n\n---\n\n".join(f"[Policy Chunk {i+1}]:\n{chunk}" for i, chunk in enumerate(chunks))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _invoke_llm(self, system: str, user: str) -> str:
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        try:
            response = invoke_groq(self._llm, messages)
            return response.content
        except GroqUnavailableError:
            logger.error(f"[{AGENT_NAME}] Groq unavailable after retry")
            return "AI service temporarily unavailable. Please try again in a moment."
        except Exception as e:
            logger.error(f"[{AGENT_NAME}] LLM invocation failed: {e}")
            raise

    @staticmethod
    def _format_lead_for_prompt(lead: dict) -> str:
        if not lead:
            return "No lead data."
        stage = lead.get("stage_id", ["", "Unknown"])
        stage_name = stage[1] if isinstance(stage, list) else str(stage)
        return (
            f"ID: {lead.get('id')}\n"
            f"Name: {lead.get('name', 'N/A')}\n"
            f"Contact: {lead.get('partner_name', 'N/A')}\n"
            f"Email: {lead.get('email_from', 'N/A')}\n"
            f"Phone: {lead.get('phone', 'N/A')}\n"
            f"Stage: {stage_name}\n"
            f"Expected Revenue: ${lead.get('expected_revenue', 0):,.2f}\n"
            f"Priority: {lead.get('priority', '0')}\n"
            f"Description/Notes: {str(lead.get('description', 'N/A'))[:500]}"
        )

    @staticmethod
    def _extract_lead_id(message: str, context: Optional[dict]) -> Optional[int]:
        if context and context.get("lead_id"):
            return int(context["lead_id"])
        import re
        patterns = [r"lead\s*#(\d+)", r"#(\d+)", r"\blead\s+(\d+)\b"]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _is_analysis_request(message: str) -> bool:
        keywords = ["analyze", "analyse", "analysis", "priority", "assess", "evaluate"]
        return any(k in message.lower() for k in keywords)

    @staticmethod
    def _is_summary_request(message: str) -> bool:
        keywords = ["summarize", "summarise", "summary", "overview", "brief", "describe"]
        return any(k in message.lower() for k in keywords)

    @staticmethod
    def _parse_section(text: str, section: str) -> Optional[str]:
        """Parse a named section from structured LLM output."""
        import re
        # Match "SECTION:\ncontent" up to the next ALL-CAPS section or end
        pattern = rf"{re.escape(section)}:\s*\n?(.*?)(?=\n[A-Z ]+:|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
