type RecentRunItem = {
  timestamp?: string;
  source?: string;
  command?: string;
  status?: string;
  message?: string;
  stop_reason?: string;
};

type Props = {
  items?: RecentRunItem[];
};

function normalizeStatus(value: string): "ok" | "fail" | "stop" | "unknown" {
  const text = String(value || "").trim().toLowerCase();
  if (text === "ok" || text === "fail" || text === "stop") {
    return text;
  }
  return "unknown";
}

export default function RecentRunsCard({ items }: Props) {
  const rows = Array.isArray(items) ? items.filter((item) => item && typeof item === "object") : [];
  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Recent Runs</h3>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-slate-300">No execution history yet.</p>
      ) : (
        <div className="mt-3 space-y-3">
          {rows.map((item, index) => {
            const status = normalizeStatus(String(item.status || ""));
            const command = String(item.command || "").trim() || "(none)";
            const source = String(item.source || "").trim();
            const message = String(item.message || "").trim();
            const stopReason = String(item.stop_reason || "").trim();
            const timestamp = String(item.timestamp || "").trim();
            return (
              <article key={`${index}-${command.slice(0, 24)}`} className="rounded-md border border-slate-700 bg-slate-950/60 p-3">
                <p className="break-words text-sm text-slate-100">
                  <span className="mr-2 inline-block rounded border border-slate-600 px-1.5 py-0.5 text-xs uppercase text-slate-200">{status}</span>
                  {command}
                </p>
                {source ? <p className="mt-1 text-xs text-slate-300">Source: {source}</p> : null}
                {message ? <p className="mt-1 break-words text-xs text-slate-300">Message: {message}</p> : null}
                {stopReason ? <p className="mt-1 break-words text-xs text-amber-300">Reason: {stopReason}</p> : null}
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
