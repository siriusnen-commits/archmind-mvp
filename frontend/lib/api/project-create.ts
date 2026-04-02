import { UI_API_BASE } from "@/components/uiApi";
import type {
  CreateProjectApiResponse,
  CreateProjectError,
  CreateProjectErrorCode,
  CreateProjectFormValues,
  CreateProjectResult,
} from "@/types/project-create";

const PROJECT_READY_TIMEOUT_MS = 15000;
const PROJECT_READY_INTERVAL_MS = 350;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function classifyCreateErrorCode(rawError: string, rawDetail: string, status: string): CreateProjectErrorCode {
  const text = `${rawError} ${rawDetail} ${status}`.toLowerCase();
  if (text.includes("idea is required") || text.includes("invalid") || text.includes("required")) {
    return "INVALID_INPUT";
  }
  if (text.includes("runtime") && (text.includes("unavailable") || text.includes("not running") || text.includes("connection"))) {
    return "RUNTIME_UNAVAILABLE";
  }
  if (text.includes("llm") || text.includes("provider") || text.includes("model unavailable")) {
    return "LLM_UNAVAILABLE";
  }
  if (text.includes("template")) {
    return "TEMPLATE_RESOLUTION_FAILED";
  }
  if (text.includes("init") || text.includes("initialize")) {
    return "PROJECT_INIT_FAILED";
  }
  if (text.includes("generation") || text.includes("generate") || text.includes("failed to start")) {
    return "GENERATION_FAILED";
  }
  return "UNKNOWN";
}

function mapErrorMessage(code: CreateProjectErrorCode, detail: string): string {
  switch (code) {
    case "INVALID_INPUT":
      return "입력값이 유효하지 않습니다. 아이디어와 필수 항목을 확인해 주세요.";
    case "RUNTIME_UNAVAILABLE":
      return "런타임이 현재 사용할 수 없습니다. 상태를 확인한 뒤 다시 시도해 주세요.";
    case "LLM_UNAVAILABLE":
      return "LLM 연결 상태를 확인할 수 없습니다. 설정에서 모드를 점검해 주세요.";
    case "TEMPLATE_RESOLUTION_FAILED":
      return "템플릿을 결정하는 중 문제가 발생했습니다.";
    case "GENERATION_FAILED":
      return "프로젝트 생성 단계에서 오류가 발생했습니다.";
    case "PROJECT_INIT_FAILED":
      return "프로젝트 초기화 단계에서 오류가 발생했습니다.";
    default:
      return detail ? `프로젝트 생성에 실패했습니다: ${detail}` : "프로젝트 생성에 실패했습니다.";
  }
}

function toStructuredError(payload: CreateProjectApiResponse, fallbackDetail = ""): CreateProjectError {
  const rawError = String(payload.error || "").trim();
  const rawDetail = String(payload.detail || "").trim() || fallbackDetail;
  const status = String(payload.status || "").trim();
  const code = classifyCreateErrorCode(rawError, rawDetail, status);
  const detail = rawError || rawDetail;
  return {
    code,
    message: mapErrorMessage(code, detail),
    detail,
    retryable: code !== "INVALID_INPUT",
    projectName: String(payload.project_name || "").trim() || undefined,
  };
}

async function isProjectDetailReady(projectName: string): Promise<boolean> {
  const target = String(projectName || "").trim();
  if (!target) {
    return false;
  }
  try {
    const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(target)}`, {
      method: "GET",
      cache: "no-store",
    });
    if (!response.ok) {
      return false;
    }
    const payload = (await response.json().catch(() => ({}))) as { name?: unknown };
    return String(payload?.name || "").trim() === target;
  } catch {
    return false;
  }
}

async function waitForProjectReady(projectName: string): Promise<boolean> {
  const deadline = Date.now() + PROJECT_READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await isProjectDetailReady(projectName)) {
      return true;
    }
    await sleep(PROJECT_READY_INTERVAL_MS);
  }
  return false;
}

async function selectCurrentProject(projectName: string): Promise<void> {
  const target = String(projectName || "").trim();
  if (!target) {
    return;
  }
  try {
    await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(target)}/select`, {
      method: "POST",
      cache: "no-store",
    });
  } catch {
    // non-fatal: detail page also sets current project on mount
  }
}

export async function createProject(values: CreateProjectFormValues): Promise<CreateProjectResult> {
  try {
    const response = await fetch(`${UI_API_BASE}/projects/idea_local`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        idea: values.idea.trim(),
        template: values.template,
        mode: values.mode,
        language: values.language,
        llm_mode: values.llmMode,
      }),
    });

    const payload = (await response.json().catch(() => ({}))) as CreateProjectApiResponse;
    if (!response.ok || !Boolean(payload.ok)) {
      return { ok: false, error: toStructuredError(payload) };
    }

    const projectName = String(payload.project_name || "").trim();
    if (!projectName) {
      return {
        ok: false,
        error: {
          code: "PROJECT_INIT_FAILED",
          message: "생성은 시작되었지만 프로젝트 식별자를 받지 못했습니다.",
          detail: "project_name missing",
          retryable: true,
        },
      };
    }

    const ready = await waitForProjectReady(projectName);
    if (!ready) {
      return {
        ok: false,
        error: {
          code: "PROJECT_INIT_FAILED",
          message: "프로젝트 생성은 시작되었지만 상세 정보가 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
          detail: "project registration did not complete in time",
          retryable: true,
          projectName,
        },
      };
    }
    await selectCurrentProject(projectName);

    return {
      ok: true,
      projectName,
      detail: String(payload.detail || "Started generation").trim(),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || "unknown error");
    return {
      ok: false,
      error: {
        code: "UNKNOWN",
        message: "요청 처리 중 네트워크 또는 서버 오류가 발생했습니다.",
        detail: message,
        retryable: true,
      },
    };
  }
}
