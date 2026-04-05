"use client";

import AgentBadge from "./AgentBadge";
import LeadCard, { Lead } from "./LeadCard";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  agentUsed?: string;
  /** Raw data returned from the API (lead or array of leads) */
  data?: Lead | Lead[] | null;
  /** Email draft HTML string */
  emailDraft?: string;
  timestamp: Date;
}

interface MessageBubbleProps {
  message: Message;
}

function stripHtml(html: string): string {
  return html.replace(/<[^>]*>/g, "").trim();
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  /* ── normalise lead data into an array ── */
  let leads: Lead[] = [];
  if (message.data) {
    if (Array.isArray(message.data)) leads = message.data as Lead[];
    else if (typeof message.data === "object" && (message.data as Lead).id)
      leads = [message.data as Lead];
  }

  const timeStr = message.timestamp.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  /* ── user bubble ── */
  if (isUser) {
    return (
      <div className="msg-in flex justify-end mb-3">
        <div className="max-w-[75%]">
          <div
            className="rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed text-white"
            style={{ backgroundColor: "#875A7B" }}
          >
            {message.content}
          </div>
          <p className="text-right text-xs mt-1" style={{ color: "#9E9E9E" }}>
            {timeStr}
          </p>
        </div>
      </div>
    );
  }

  /* ── assistant bubble ── */
  return (
    <div className="msg-in flex justify-start mb-3">
      {/* Avatar */}
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 mr-2.5 mt-0.5 text-white"
        style={{ backgroundColor: "#875A7B" }}
      >
        AI
      </div>

      <div className="max-w-[80%]">
        {/* Agent badge */}
        {message.agentUsed && <AgentBadge agentName={message.agentUsed} />}

        {/* Text content */}
        <div
          className="rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap border"
          style={{ backgroundColor: "#FFFFFF", borderColor: "#D5D5D5", color: "#1D1D1D" }}
        >
          {message.content}
        </div>

        {/* Lead cards */}
        {leads.length > 0 && (
          <div className="mt-2">
            {leads.map((lead, i) => (
              <LeadCard key={lead.id ?? i} lead={lead} />
            ))}
          </div>
        )}

        {/* Email draft */}
        {message.emailDraft && (
          <div
            className="mt-2 rounded-lg border p-3 text-xs"
            style={{ backgroundColor: "#F5EBF2", borderColor: "#C49AB8" }}
          >
            <p className="font-semibold mb-1.5 text-xs uppercase tracking-wide" style={{ color: "#875A7B" }}>
              Email Draft
            </p>
            <pre className="whitespace-pre-wrap font-sans leading-relaxed" style={{ color: "#1D1D1D" }}>
              {stripHtml(message.emailDraft)}
            </pre>
          </div>
        )}

        <p className="text-xs mt-1" style={{ color: "#9E9E9E" }}>
          {timeStr}
        </p>
      </div>
    </div>
  );
}
