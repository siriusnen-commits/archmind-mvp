"use client";

import { useState } from "react";

type ProviderMode = "local" | "cloud" | "auto";

type Props = {
  projectName: string;
  mode: ProviderMode;
  apiBaseUrl: string;
  onUpdated?: (mode: ProviderMode) => void;
};

export default function ProviderCard({ projectName, mode, apiBaseUrl, onUpdated }: Props) {
  const [currentMode, setCurrentMode] = useState<ProviderMode>(mode);
  const [loading, setLoading] = useState(false);

  const updateMode = async (nextMode: ProviderMode) => {
    setLoading(true);
    try {
      const endpoint =
        apiBaseUrl + "/ui/projects/" + encodeURIComponent(projectName) + "/provider";
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: nextMode }),
      });
      if (response.ok) {
        const payload = (await response.json()) as { mode: ProviderMode };
        setCurrentMode(payload.mode);
        onUpdated?.(payload.mode);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
      <h3 style={{ marginTop: 0 }}>Provider</h3>
      <div style={{ marginBottom: 8 }}>Mode: {currentMode}</div>
      <div style={{ display: "flex", gap: 8 }}>
        {(["local", "cloud", "auto"] as ProviderMode[]).map((item) => (
          <button
            key={item}
            type="button"
            disabled={loading || item === currentMode}
            onClick={() => updateMode(item)}
            style={{
              border: item === currentMode ? "1px solid #111" : "1px solid #ddd",
              borderRadius: 6,
              padding: "6px 10px",
              background: item === currentMode ? "#f6f6f6" : "#fff",
              cursor: "pointer",
            }}
          >
            {item}
          </button>
        ))}
      </div>
    </div>
  );
}
