"use client";

// Agent badge styles — light backgrounds for Odoo white theme
const AGENT_STYLES: Record<string, { label: string; bg: string; text: string; border: string }> = {
  DataRetrieverAgent:   { label: "Data Retriever",     bg: "#EBF3FB", text: "#1A6EA8", border: "#A8CCEA" },
  TaskExecutorAgent:    { label: "Task Executor",      bg: "#EBF6EC", text: "#2E7D32", border: "#A5D6A7" },
  ActionValidatorAgent: { label: "Action Validator",   bg: "#FFF3E0", text: "#E65100", border: "#FFCC80" },
  CommunicationAgent:   { label: "Communication Agent", bg: "#F5EBF2", text: "#875A7B", border: "#C49AB8" },
  RouterAgent:          { label: "Router Agent",       bg: "#F5F5F5", text: "#555555", border: "#BDBDBD" },
};

const DEFAULT_STYLE = { label: "AI Agent", bg: "#F5F5F5", text: "#555555", border: "#BDBDBD" };

interface AgentBadgeProps {
  agentName: string;
}

export default function AgentBadge({ agentName }: AgentBadgeProps) {
  const style = AGENT_STYLES[agentName] ?? DEFAULT_STYLE;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border mb-1.5"
      style={{ backgroundColor: style.bg, color: style.text, borderColor: style.border }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: style.text }}
      />
      {style.label}
    </span>
  );
}
