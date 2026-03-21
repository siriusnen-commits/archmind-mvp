type Props = {
  items?: string[];
};

export default function EvolutionCard({ items }: Props) {
  const list = Array.isArray(items) ? items.filter((item) => String(item || "").trim().length > 0) : [];

  return (
    <section className="rounded-md border border-zinc-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-zinc-900">Recent Evolution</h3>
      {list.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-600">(none)</p>
      ) : (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-zinc-800">
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
