"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import MessageBubble, { Message } from "./MessageBubble";
import SuggestionChips from "./SuggestionChips";
import { Lead } from "./LeadCard";

const API_BASE = "http://localhost:8000";
const SESSION_ID = "web-user-1";

type BackendStatus = "checking" | "online" | "offline";

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

/** Parse the FastAPI /api/chat response into a Message */
function parseApiResponse(raw: Record<string, unknown>): Omit<Message, "id" | "timestamp"> {
  const text =
    typeof raw.response === "string"
      ? raw.response
      : typeof raw.message === "string"
      ? raw.message
      : JSON.stringify(raw, null, 2);

  const agentUsed =
    typeof raw.agent_used === "string" ? raw.agent_used : undefined;

  // Lead data: could be raw.data (single or array)
  let data: Lead | Lead[] | null = null;
  if (raw.data) {
    data = raw.data as Lead | Lead[];
  }

  // Email draft
  const emailDraft =
    typeof raw.email_draft === "string" && raw.email_draft
      ? raw.email_draft
      : undefined;

  return { role: "assistant", content: text, agentUsed, data, emailDraft };
}

export default function ChatInterface() {
  const [messages, setMessages]     = useState<Message[]>([]);
  const [input, setInput]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [status, setStatus]         = useState<BackendStatus>("checking");

  const bottomRef  = useRef<HTMLDivElement>(null);
  const inputRef   = useRef<HTMLTextAreaElement>(null);

  /* ── Check backend health on mount ───────────────────────── */
  useEffect(() => {
    fetch(`${API_BASE}/api/status`, { signal: AbortSignal.timeout(4000) })
      .then((r) => {
        setStatus(r.ok ? "online" : "offline");
        if (r.ok) {
          setMessages([
            {
              id: makeId(),
              role: "assistant",
              content:
                "Hello! I'm your ERP AI Assistant. I'm connected to Odoo CRM and ready to help.\n\nYou can ask me to:\n• Show or search leads\n• Create or update a lead\n• Analyze and prioritize a lead\n• Draft a professional follow-up email\n\nWhat would you like to do?",
              agentUsed: "RouterAgent",
              timestamp: new Date(),
            },
          ]);
        } else {
          setMessages([offlineMessage()]);
        }
      })
      .catch(() => {
        setStatus("offline");
        setMessages([offlineMessage()]);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Auto-scroll ──────────────────────────────────────────── */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  /* ── Send message ─────────────────────────────────────────── */
  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;

      const userMsg: Message = {
        id: makeId(),
        role: "user",
        content: trimmed,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setLoading(true);

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: trimmed, session_id: SESSION_ID }),
          signal: AbortSignal.timeout(30000),
        });

        if (!res.ok) {
          throw new Error(`Server returned ${res.status}`);
        }

        const raw: Record<string, unknown> = await res.json();
        const parsed = parseApiResponse(raw);
        setMessages((prev) => [...prev, { id: makeId(), timestamp: new Date(), ...parsed }]);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        setMessages((prev) => [
          ...prev,
          {
            id: makeId(),
            role: "assistant",
            content: `Sorry, I couldn't reach the backend. ${msg}`,
            timestamp: new Date(),
          },
        ]);
      } finally {
        setLoading(false);
        inputRef.current?.focus();
      }
    },
    [loading]
  );

  /* ── Chip selection: fill + auto-send ─────────────────────── */
  const handleChipSelect = useCallback(
    (chip: string) => {
      sendMessage(chip);
    },
    [sendMessage]
  );

  /* ── Textarea: Enter sends, Shift+Enter = newline ─────────── */
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  /* ── Status dot helpers ───────────────────────────────────── */
  const dotColor =
    status === "online" ? "bg-green-400 status-pulse" :
    status === "offline" ? "bg-red-500" :
    "bg-yellow-400";

  const statusLabel =
    status === "online" ? "Online" :
    status === "offline" ? "Backend Offline" :
    "Connecting…";

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: "#E0E0E0" }}>

      {/* ── Header ── */}
      <header
        className="shrink-0 flex items-center justify-between px-5 py-3.5 border-b"
        style={{ backgroundColor: "#875A7B", borderColor: "#714B67" }}
      >
        <div className="flex items-center gap-3">
          {/* Logo mark */}
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm text-white"
            style={{ backgroundColor: "#714B67" }}
          >
            ERP
          </div>
          <div>
            <h1 className="font-semibold text-white text-sm leading-tight">
              ERP AI Assistant
            </h1>
            <p className="text-xs" style={{ color: "#F0E0EC" }}>
              Multi-Agent System
            </p>
          </div>
        </div>

        {/* Status indicator */}
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${dotColor}`} />
          <span className="text-xs" style={{ color: "#F0E0EC" }}>
            {statusLabel}
          </span>
        </div>
      </header>

      {/* ── Message list ── */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1" style={{ backgroundColor: "#E0E0E0" }}>
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Thinking indicator */}
        {loading && (
          <div className="msg-in flex justify-start mb-3">
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 mr-2.5 text-white"
              style={{ backgroundColor: "#875A7B" }}
            >
              AI
            </div>
            <div
              className="rounded-2xl rounded-tl-sm px-4 py-3 text-sm flex items-center gap-2 border"
              style={{ backgroundColor: "#FFFFFF", borderColor: "#C49AB8", color: "#6C6C6C" }}
            >
              <span className="dot-1 text-lg leading-none" style={{ color: "#875A7B" }}>·</span>
              <span className="dot-2 text-lg leading-none" style={{ color: "#875A7B" }}>·</span>
              <span className="dot-3 text-lg leading-none" style={{ color: "#875A7B" }}>·</span>
              <span className="ml-1 text-xs">Agent is thinking…</span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Suggestion chips ── */}
      {!loading && <SuggestionChips onSelect={handleChipSelect} disabled={loading} />}

      {/* ── Input bar ── */}
      <div
        className="shrink-0 px-4 py-3 border-t"
        style={{ backgroundColor: "#FFFFFF", borderColor: "#D5D5D5" }}
      >
        <div
          className="flex items-end gap-3 rounded-xl border px-4 py-2.5"
          style={{ backgroundColor: "#FFFFFF", borderColor: "#C49AB8" }}
        >
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              // auto-grow up to ~120px
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
            }}
            onKeyDown={handleKeyDown}
            placeholder='Ask anything — e.g. "Show high priority leads" or "Analyze lead #5"'
            disabled={loading || status === "offline"}
            className="chat-input flex-1 resize-none bg-transparent text-sm leading-relaxed disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ color: "#1D1D1D", caretColor: "#875A7B", minHeight: "24px" }}
          />

          <button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim() || status === "offline"}
            className="shrink-0 w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 cursor-pointer"
            style={{ backgroundColor: "#875A7B" }}
            aria-label="Send"
          >
            {/* Send icon */}
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>

        <p className="text-center text-xs mt-2" style={{ color: "#9E9E9E" }}>
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}

/* ── helpers ── */
function offlineMessage(): Message {
  return {
    id: makeId(),
    role: "assistant",
    content:
      "Backend is offline. Make sure FastAPI is running:\n\n  cd erp-ai-backend\n  uvicorn main:app --reload --port 8000",
    timestamp: new Date(),
  };
}
