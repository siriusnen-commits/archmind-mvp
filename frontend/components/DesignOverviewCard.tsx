type DesignOverview = {
  architecture_summary?: string;
  entities?: string[];
  apis?: string[];
  pages?: string[];
  notes?: string;
};

type Props = {
  design?: DesignOverview | null;
};

function toRows(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item || "").trim())
    .filter((item) => Boolean(item));
}

function ItemList({ title, rows, emptyText }: { title: string; rows: string[]; emptyText: string }) {
  return (
    <div className="space-y-2 rounded border border-slate-700 bg-slate-950/40 p-3">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">{title}</h4>
      {rows.length === 0 ? (
        <p className="text-xs text-slate-400">{emptyText}</p>
      ) : (
        <ul className="list-disc space-y-1 pl-4 text-sm text-slate-200">
          {rows.slice(0, 12).map((row, idx) => (
            <li key={`${row}-${idx}`} className="break-all">
              {row}
            </li>
          ))}
          {rows.length > 12 ? <li className="text-xs text-slate-400">+{rows.length - 12} more</li> : null}
        </ul>
      )}
    </div>
  );
}

export default function DesignOverviewCard({ design }: Props) {
  const row = design && typeof design === "object" ? design : {};
  const architectureSummary = String(row.architecture_summary || "").trim();
  const entities = toRows(row.entities);
  const apis = toRows(row.apis);
  const pages = toRows(row.pages);
  const notes = String(row.notes || "").trim();
  const hasAny = Boolean(architectureSummary || notes || entities.length || apis.length || pages.length);

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Design Overview</h3>
      {!hasAny ? <p className="mt-2 text-sm text-slate-300">No design result yet. Run /design to generate architecture guidance.</p> : null}

      {hasAny ? (
        <div className="mt-3 space-y-3">
          <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Architecture Summary</h4>
            <p className="mt-1 text-sm text-slate-200">{architectureSummary || "No architecture summary available."}</p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <ItemList title="Entities" rows={entities} emptyText="No entities in design." />
            <ItemList title="APIs" rows={apis} emptyText="No APIs in design." />
            <ItemList title="Pages" rows={pages} emptyText="No pages in design." />
            <div className="space-y-2 rounded border border-slate-700 bg-slate-950/40 p-3">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Notes</h4>
              <p className="text-sm text-slate-200">{notes || "No design notes available."}</p>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
