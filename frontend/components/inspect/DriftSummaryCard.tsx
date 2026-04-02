type VerificationOverview = {
  drift_summary?: string;
  status_counts?: {
    verified?: number;
    partial?: number;
    failed?: number;
  };
};

type Props = {
  verification?: VerificationOverview;
};

export default function DriftSummaryCard({ verification }: Props) {
  const summary = String(verification?.drift_summary || "").trim();
  const counts = verification?.status_counts || {};
  const verified = Number(counts.verified || 0);
  const partial = Number(counts.partial || 0);
  const failed = Number(counts.failed || 0);
  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Drift Summary</h3>
      <p className="mt-2 text-sm text-slate-200">VERIFIED {verified} · PARTIAL {partial} · FAILED {failed}</p>
      <p className="mt-1 text-xs text-slate-300">{summary || "No drift summary available."}</p>
    </section>
  );
}
