"use client";

export interface Lead {
  id?: number;
  name?: string;
  partner_name?: string;
  email_from?: string;
  phone?: string;
  priority?: string;
  stage_id?: [number, string] | string;
  expected_revenue?: number;
  probability?: number;
  description?: string;
  ai_priority_prediction?: string;
  ai_summary?: string;
}

const PRIORITY_MAP: Record<string, { label: string; border: string; bg: string; dot: string; text: string }> = {
  "2":    { label: "High",   border: "#FFCDD2", bg: "#FFF5F5", dot: "#E53935", text: "#C62828" },
  "1":    { label: "Medium", border: "#FFE082", bg: "#FFFDE7", dot: "#F9A825", text: "#E65100" },
  "0":    { label: "Low",    border: "#C8E6C9", bg: "#F1F8F1", dot: "#43A047", text: "#2E7D32" },
  "high":   { label: "High",   border: "#FFCDD2", bg: "#FFF5F5", dot: "#E53935", text: "#C62828" },
  "medium": { label: "Medium", border: "#FFE082", bg: "#FFFDE7", dot: "#F9A825", text: "#E65100" },
  "low":    { label: "Low",    border: "#C8E6C9", bg: "#F1F8F1", dot: "#43A047", text: "#2E7D32" },
};

const DEFAULT_PRIORITY = { label: "—", border: "#D5D5D5", bg: "#FFFFFF", dot: "#9E9E9E", text: "#555555" };

interface LeadCardProps {
  lead: Lead;
}

export default function LeadCard({ lead }: LeadCardProps) {
  const pKey = lead.ai_priority_prediction ?? lead.priority ?? "0";
  const pStyle = PRIORITY_MAP[pKey] ?? DEFAULT_PRIORITY;
  const stageName = Array.isArray(lead.stage_id) ? lead.stage_id[1] : (lead.stage_id ?? "—");
  const revenue = lead.expected_revenue
    ? `$${Number(lead.expected_revenue).toLocaleString()}`
    : "—";

  return (
    <div
      className="rounded-lg border p-3 mb-2 text-sm"
      style={{ backgroundColor: pStyle.bg, borderColor: pStyle.border }}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <span className="font-semibold" style={{ color: "#1D1D1D" }}>
            {lead.name ?? "Unnamed Lead"}
          </span>
          {lead.id && (
            <span className="ml-2 text-xs" style={{ color: "#9E9E9E" }}>#{lead.id}</span>
          )}
        </div>
        {/* Priority badge */}
        <span
          className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium shrink-0 border"
          style={{ backgroundColor: pStyle.bg, borderColor: pStyle.border, color: pStyle.text }}
        >
          <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: pStyle.dot }} />
          {pStyle.label}
        </span>
      </div>

      {/* Fields grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs" style={{ color: "#1D1D1D" }}>
        {lead.partner_name && (
          <div><span style={{ color: "#6C6C6C" }}>Contact: </span>{lead.partner_name}</div>
        )}
        {lead.email_from && (
          <div><span style={{ color: "#6C6C6C" }}>Email: </span>{lead.email_from}</div>
        )}
        {lead.phone && (
          <div><span style={{ color: "#6C6C6C" }}>Phone: </span>{lead.phone}</div>
        )}
        {stageName !== "—" && (
          <div><span style={{ color: "#6C6C6C" }}>Stage: </span>{stageName}</div>
        )}
        {lead.expected_revenue !== undefined && (
          <div><span style={{ color: "#6C6C6C" }}>Revenue: </span>{revenue}</div>
        )}
        {lead.probability !== undefined && (
          <div><span style={{ color: "#6C6C6C" }}>Probability: </span>{lead.probability}%</div>
        )}
      </div>

      {/* AI summary strip */}
      {lead.ai_summary && (
        <div
          className="mt-2 pt-2 border-t text-xs"
          style={{ borderColor: "#C49AB8", color: "#875A7B" }}
        >
          <span style={{ color: "#6C6C6C" }}>AI: </span>
          {lead.ai_summary.slice(0, 160)}{lead.ai_summary.length > 160 ? "…" : ""}
        </div>
      )}
    </div>
  );
}
