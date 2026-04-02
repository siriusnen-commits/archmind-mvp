"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import CreateProjectErrorCard from "@/components/new-project/CreateProjectErrorCard";
import CreateProjectStatusCard from "@/components/new-project/CreateProjectStatusCard";
import NewProjectForm from "@/components/new-project/NewProjectForm";
import { createProject } from "@/lib/api/project-create";
import { buildCreateDefaults, loadSettings } from "@/lib/api/settings";
import type { CreateProjectError, CreateProjectFormValues, CreateProjectStage } from "@/types/project-create";
import type { UiLanguage } from "@/types/settings";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

const INITIAL_VALUES: CreateProjectFormValues = {
  idea: "",
  template: "auto",
  mode: "balanced",
  language: "english",
  llmMode: "local",
};

export default function NewProjectPage() {
  const router = useRouter();
  const [uiLanguage] = useState<UiLanguage>(() => loadSettings().uiLanguage);
  const [stage, setStage] = useState<CreateProjectStage>("idle");
  const [values, setValues] = useState<CreateProjectFormValues>(() => {
    const settings = loadSettings();
    const defaults = buildCreateDefaults(settings);
    return {
      ...INITIAL_VALUES,
      template: defaults.template,
      mode: defaults.mode,
      language: defaults.language,
      llmMode: defaults.llmMode,
    };
  });
  const [error, setError] = useState<CreateProjectError | null>(null);

  const creating = useMemo(() => {
    return stage !== "idle" && stage !== "failed" && stage !== "completed";
  }, [stage]);

  async function runCreateFlow() {
    const trimmedIdea = values.idea.trim();
    setError(null);

    setStage("validating");
    if (trimmedIdea.length === 0) {
      setStage("failed");
      setError({
        code: "INVALID_INPUT",
        message: uiLanguage === "ko" ? "아이디어를 입력해 주세요." : uiLanguage === "ja" ? "アイデアを入力してください。" : "Please enter an idea.",
        detail: "idea is required",
        retryable: false,
      });
      return;
    }

    setStage("checking-runtime");
    await sleep(120);
    setStage("resolving-template");
    await sleep(120);
    setStage("generating");

    const result = await createProject(values);
    if (!result.ok) {
      setStage("failed");
      setError(result.error);
      return;
    }

    setStage("initializing");
    await sleep(150);
    setStage("completed");

    router.push(`/projects/${encodeURIComponent(result.projectName)}`);
    router.refresh();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (creating) {
      return;
    }
    await runCreateFlow();
  }

  async function onRetry() {
    if (creating) {
      return;
    }
    await runCreateFlow();
  }

  function onEditInputs() {
    setStage("idle");
  }

  function onOpenSettings() {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("archmind:open-settings"));
    }
  }

  function onOpenLogs() {
    const targetProject = String(error?.projectName || "").trim();
    if (targetProject) {
      router.push(`/projects/${encodeURIComponent(targetProject)}`);
      return;
    }
    router.push("/dashboard");
  }

  function onBackToDashboard() {
    router.push("/dashboard");
  }

  return (
    <main className="mx-auto w-full max-w-3xl p-4 sm:p-6">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">
            {uiLanguage === "ko" ? "새 프로젝트" : uiLanguage === "ja" ? "新しいプロジェクト" : "New Project"}
          </h1>
          <p className="mt-1 text-sm text-slate-300">
            {uiLanguage === "ko"
              ? "아이디어 기반 프로젝트 생성을 시작합니다."
              : uiLanguage === "ja"
                ? "アイデアから新規プロジェクトを生成します。"
                : "Create a project from your idea."}
          </p>
        </div>
        <Link href="/dashboard" className="rounded-md border border-slate-500 px-3 py-1.5 text-sm text-slate-100 hover:bg-slate-800">
          {uiLanguage === "ko" ? "뒤로" : uiLanguage === "ja" ? "戻る" : "Back"}
        </Link>
      </header>

      <div className="space-y-3">
        <CreateProjectStatusCard stage={stage} uiLanguage={uiLanguage} />
        <NewProjectForm values={values} onChange={setValues} onSubmit={onSubmit} disabled={creating} uiLanguage={uiLanguage} />
        {error ? (
          <CreateProjectErrorCard
            error={error}
            onRetry={onRetry}
            onEditInputs={onEditInputs}
            onOpenSettings={onOpenSettings}
            onOpenLogs={onOpenLogs}
            onBackToDashboard={onBackToDashboard}
            busy={creating}
            uiLanguage={uiLanguage}
          />
        ) : null}
      </div>
    </main>
  );
}
