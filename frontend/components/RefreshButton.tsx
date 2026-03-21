"use client";

type Props = {
  label?: string;
  className?: string;
};

export default function RefreshButton({ label = "Refresh", className = "" }: Props) {
  return (
    <button
      type="button"
      onClick={() => window.location.reload()}
      className={className}
    >
      {label}
    </button>
  );
}
