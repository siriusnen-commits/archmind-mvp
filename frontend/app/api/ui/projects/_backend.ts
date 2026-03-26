const DEFAULT_BACKEND_UI_BASE = "http://127.0.0.1:8000/ui";

export function getBackendUiBase(): string {
  const raw = String(process.env.ARCHMIND_UI_API_BASE || "").trim();
  const normalized = raw.replace(/\/$/, "");
  return normalized || DEFAULT_BACKEND_UI_BASE;
}
