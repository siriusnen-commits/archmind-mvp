type Props = {
  status?: string;
};

function normalize(value: string): string {
  const text = String(value || "").trim().toUpperCase();
  if (text === "VERIFIED" || text === "PARTIAL" || text === "FAILED") {
    return text;
  }
  return "UNKNOWN";
}

function tone(status: string): string {
  if (status === "VERIFIED") return "border-emerald-500/50 text-emerald-200";
  if (status === "FAILED") return "border-rose-500/50 text-rose-200";
  if (status === "PARTIAL") return "border-amber-500/50 text-amber-200";
  return "border-slate-600 text-slate-300";
}

export default function VerificationBadge({ status }: Props) {
  const normalized = normalize(String(status || ""));
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] uppercase ${tone(normalized)}`}>{normalized}</span>;
}
