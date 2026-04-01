import type { GenerationMode, LlmMode, ProjectLanguage, TemplateOption } from "@/types/settings";

export type CreateProjectStage =
  | "idle"
  | "validating"
  | "checking-runtime"
  | "resolving-template"
  | "generating"
  | "initializing"
  | "completed"
  | "failed";

export type CreateProjectErrorCode =
  | "INVALID_INPUT"
  | "RUNTIME_UNAVAILABLE"
  | "LLM_UNAVAILABLE"
  | "TEMPLATE_RESOLUTION_FAILED"
  | "GENERATION_FAILED"
  | "PROJECT_INIT_FAILED"
  | "UNKNOWN";

export type CreateProjectFormValues = {
  idea: string;
  template: TemplateOption;
  mode: GenerationMode;
  language: ProjectLanguage;
  llmMode: LlmMode;
};

export type CreateProjectError = {
  code: CreateProjectErrorCode;
  message: string;
  detail?: string;
  retryable: boolean;
  projectName?: string;
};

export type CreateProjectApiResponse = {
  ok?: boolean;
  project_name?: string;
  detail?: string;
  error?: string;
  status?: string;
  request?: {
    idea?: string;
    template?: string;
    mode?: string;
    language?: string;
    llm_mode?: string;
  };
};

export type CreateProjectResult =
  | {
      ok: true;
      projectName: string;
      detail: string;
    }
  | {
      ok: false;
      error: CreateProjectError;
    };
