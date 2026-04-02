type VerificationOverview = {
  latest_status?: string;
  runtime_reflection?: string;
  latest_issues?: string[];
};

type Props = {
  verification?: VerificationOverview;
};

export default function RuntimeConsistencyCard({ verification }: Props) {
  const latestStatus = String(verification?.latest_status || "UNKNOWN").trim().toUpperCase();
  const runtimeReflection = String(verification?.runtime_reflection || "unknown").trim() || "unknown";
  const issues = Array.isArray(verification?.latest_issues)
    ? verification!.latest_issues!.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 3)
    : [];
  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Runtime Consistency</h3>
      <p className="mt-2 text-sm text-slate-200">Latest verification: {latestStatus}</p>
      <p className="text-xs text-slate-400">Runtime reflection: {runtimeReflection}</p>
      {issues.length > 0 ? <p className="mt-1 text-xs text-amber-300">Issues: {issues.join("; ")}</p> : <p className="mt-1 text-xs text-emerald-300">No critical runtime drift detected.</p>}
    </section>
  );
}
