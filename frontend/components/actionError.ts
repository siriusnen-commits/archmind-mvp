export type UiActionError = {
  kind: "backend_unavailable" | "request_failure" | "malformed_response" | "execution_failure";
  message: string;
  hint: string;
};

function toText(value: unknown): string {
  return String(value || "").trim();
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

export function classifyActionFailure(
  response: Response,
  payload: unknown,
  options: { actionLabel: string; includeLogsHint?: boolean },
): UiActionError {
  const actionLabel = toText(options.actionLabel) || "Action";
  const includeLogsHint = Boolean(options.includeLogsHint);
  const detail = isObject(payload) ? toText(payload.detail) : "";
  const error = isObject(payload) ? toText(payload.error) : "";
  const message = detail || error;

  if (!isObject(payload)) {
    return {
      kind: "malformed_response",
      message: `${actionLabel} failed: malformed response from backend.`,
      hint: "Retry once. If it persists, restart backend runtime.",
    };
  }

  if (!response.ok) {
    if (response.status >= 500) {
      return {
        kind: "backend_unavailable",
        message: `${actionLabel} failed: backend is unavailable or returned server error.`,
        hint: "Check Runtime status and start backend if needed.",
      };
    }
    return {
      kind: "request_failure",
      message: `${actionLabel} failed: ${message || `request error (${response.status})`}.`,
      hint: "Verify input and retry.",
    };
  }

  return {
    kind: "execution_failure",
    message: `${actionLabel} failed: ${message || "execution failed"}.`,
    hint: includeLogsHint ? "Open Logs Viewer for details, then retry." : "Review details and retry.",
  };
}

export function classifyNetworkFailure(
  error: unknown,
  options: { actionLabel: string; includeLogsHint?: boolean },
): UiActionError {
  const actionLabel = toText(options.actionLabel) || "Action";
  const includeLogsHint = Boolean(options.includeLogsHint);
  const raw = toText(error instanceof Error ? error.message : error);
  const lowered = raw.toLowerCase();
  if (
    lowered.includes("failed to fetch") ||
    lowered.includes("networkerror") ||
    lowered.includes("load failed") ||
    lowered.includes("network request failed")
  ) {
    return {
      kind: "backend_unavailable",
      message: `${actionLabel} failed: backend is not reachable.`,
      hint: "Check Runtime status and start backend if needed.",
    };
  }
  return {
    kind: "request_failure",
    message: `${actionLabel} failed: ${raw || "request failed"}.`,
    hint: includeLogsHint ? "Open Logs Viewer and retry." : "Retry the request.",
  };
}
