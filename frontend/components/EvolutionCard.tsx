type Props = {
  items?: string[];
};

export default function EvolutionCard({ items }: Props) {
  const list = Array.isArray(items) ? items.filter((item) => String(item || "").trim().length > 0) : [];

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Recent Evolution</h3>
      {list.length === 0 ? (
        <p className="mt-3 text-sm text-slate-300">(none)</p>
      ) : (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-200">
          {list.map((item, index) => (
            <li key={`${index}-${item.slice(0, 16)}`} className="break-words">
              {item}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
