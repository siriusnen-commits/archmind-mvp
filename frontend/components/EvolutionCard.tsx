"use client";

type Props = {
  items: string[];
};

export default function EvolutionCard({ items }: Props) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
      <h3 style={{ marginTop: 0 }}>Recent Evolution</h3>
      {items.length === 0 ? (
        <div style={{ color: "#666" }}>(none)</div>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {items.map((item, index) => (
            <li key={index} style={{ overflowWrap: "anywhere" }}>
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
