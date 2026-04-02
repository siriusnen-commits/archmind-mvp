type Props = {
  issues?: string[];
};

export default function VerificationIssues({ issues }: Props) {
  const rows = Array.isArray(issues) ? issues.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 3) : [];
  if (rows.length === 0) return null;
  return (
    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-amber-200">
      {rows.map((item, idx) => (
        <li key={`${idx}-${item.slice(0, 24)}`}>{item}</li>
      ))}
    </ul>
  );
}
