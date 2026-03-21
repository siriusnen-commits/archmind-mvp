"use client";

import { useRouter } from "next/navigation";

type Props = {
  label?: string;
  className?: string;
};

export default function RefreshButton({ label = "Refresh", className = "" }: Props) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => router.refresh()}
      className={className}
    >
      {label}
    </button>
  );
}
