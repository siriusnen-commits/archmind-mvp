"use client";

type EvolutionHistoryItem = {
  timestamp?: string;
  title?: string;
  status?: string;
  summary?: string;
  action_type?: string;
  command?: string;
  source?: string;
  stop_reason?: string;
};

type Props = {
  items?: EvolutionHistoryItem[];
};

function normalizeStatus(value: string): string {
  const text = String(value || "").trim().toUpperCase();
  if (text === "OK" || text === "FAILED" || text === "STOPPED" || text === "SYNCED" || text === "COMMIT_ONLY" || text === "PUSH_FAILED") {
    return text;
  }
  return "UNKNOWN";
}

function statusBadgeClass(status: string): string {
  if (status === "OK" || status === "SYNCED") {
    return "border-emerald-500/50 text-emerald-200";
  }
  if (status === "FAILED" || status === "PUSH_FAILED") {
    return "border-rose-500/50 text-rose-200";
  }
  if (status === "STOPPED" || status === "COMMIT_ONLY") {
    return "border-amber-500/50 text-amber-200";
  }
  return "border-slate-600 text-slate-200";
}

export default function EvolutionHistoryCard({ items }: Props) {
  const rows = Array.isArray(items) ? items.filter((item) => item && typeof item === "object").slice(0, 12) : [];
  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Evolution History</h3>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-slate-300">No evolution history yet.</p>
      ) : (
        <div className="mt-3 space-y-3">
          {rows.map((item, index) => {
            const status = normalizeStatus(String(item.status || ""));
            const title = String(item.title || item.command || "").trim() || "Unknown action";
            const summary = String(item.summary || "").trim();
            const command = String(item.command || "").trim();
            const source = String(item.source || "").trim();
            const actionType = String(item.action_type || "").trim();
            const stopReason = String(item.stop_reason || "").trim();
            const timestamp = String(item.timestamp || "").trim();
            return (
              <article key={`${index}-${title.slice(0, 24)}`} className="rounded-md border border-slate-700 bg-slate-950/60 p-3">
                <p className="break-words text-sm text-slate-100">
                  <span className={`mr-2 inline-block rounded border px-1.5 py-0.5 text-xs uppercase ${statusBadgeClass(status)}`}>{status}</span>
                  {title}
                </p>
                {summary ? <p className="mt-1 break-words text-xs text-slate-300">Summary: {summary}</p> : null}
                {actionType ? <p className="mt-1 text-xs text-slate-300">Type: {actionType}</p> : null}
                {command && command !== title ? <p className="mt-1 break-words text-xs text-slate-300">Command: {command}</p> : null}
                {source ? <p className="mt-1 text-xs text-slate-400">Source: {source}</p> : null}
                {stopReason && stopReason !== summary ? <p className="mt-1 break-words text-xs text-amber-300">Stop: {stopReason}</p> : null}
                {timestamp ? (
                  <p className="mt-1 text-xs text-slate-400" suppressHydrationWarning>
                    {timestamp}
                  </p>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
