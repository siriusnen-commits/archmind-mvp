"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type ProviderMode = "local" | "cloud" | "auto";

type Props = {
  projectName?: string;
  mode?: ProviderMode | string;
};

const API_BASE =
  process.env.NEXT_PUBLIC_ARCHMIND_UI_API_BASE ||
  "http://127.0.0.1:8010/ui";

export default function ProviderCard({ projectName, mode }: Props) {
  const router = useRouter();
  const [currentMode, setCurrentMode] = useState<ProviderMode>(normalizeMode(mode));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setCurrentMode(normalizeMode(mode));
  }, [mode]);

  async function updateMode(nextMode: ProviderMode) {
    if (!projectName) {
      setError("Failed to update provider");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const endpoint = `${API_BASE}/projects/${encodeURIComponent(projectName)}/provider`;
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: nextMode }),
      });
      if (!response.ok) {
        setError("Failed to update provider");
        return;
      }
      const payload = (await response.json()) as { mode?: string };
      setCurrentMode(normalizeMode(payload.mode || nextMode));
      router.refresh();
    } catch {
      setError("Failed to update provider");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-md border border-zinc-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-zinc-900">Provider</h3>
      <p className="mt-2 text-sm text-zinc-700">Mode: {currentMode}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {(["local", "cloud", "auto"] as ProviderMode[]).map((item) => {
          const selected = item === currentMode;
          return (
            <button
              key={item}
              type="button"
              disabled={loading || selected}
              onClick={() => updateMode(item)}
              className={[
                "rounded-md border px-3 py-1.5 text-sm",
                selected
                  ? "border-zinc-900 bg-zinc-900 text-white"
                  : "border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-50",
                loading ? "opacity-60" : "",
              ].join(" ")}
            >
              {item}
            </button>
          );
        })}
      </div>
      {error ? <p className="mt-2 text-xs text-red-600">{error}</p> : null}
    </section>
  );
}

function normalizeMode(value: unknown): ProviderMode {
  const mode = String(value || "").trim().toLowerCase();
  if (mode === "cloud" || mode === "auto") {
    return mode;
  }
  return "local";
}
