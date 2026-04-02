"use client";

import type { CreateProjectError } from "@/types/project-create";
import type { UiLanguage } from "@/types/settings";

type Props = {
  error: CreateProjectError;
  onRetry: () => void;
  onEditInputs: () => void;
  onOpenSettings: () => void;
  onOpenLogs: () => void;
  onBackToDashboard: () => void;
  busy?: boolean;
  uiLanguage?: UiLanguage;
};

export default function CreateProjectErrorCard({
  error,
  onRetry,
  onEditInputs,
  onOpenSettings,
  onOpenLogs,
  onBackToDashboard,
  busy = false,
  uiLanguage = "en",
}: Props) {
  const text =
    uiLanguage === "ko"
      ? {
          title: "생성 실패",
          detail: "상세",
          code: "오류 코드",
          retry: "재시도",
          edit: "입력 수정",
          settings: "설정 열기",
          logs: "로그 보기",
          back: "대시보드로 돌아가기",
        }
      : uiLanguage === "ja"
        ? {
            title: "生成失敗",
            detail: "詳細",
            code: "エラーコード",
            retry: "再試行",
            edit: "入力を編集",
            settings: "設定を開く",
            logs: "ログを開く",
            back: "ダッシュボードへ戻る",
          }
        : {
            title: "Creation Failed",
            detail: "Detail",
            code: "Error Code",
            retry: "Retry",
            edit: "Edit inputs",
            settings: "Open settings",
            logs: "Open logs",
            back: "Back to dashboard",
          };
  return (
    <section className="rounded-lg border border-rose-700 bg-rose-950/40 p-4">
      <h2 className="text-sm font-semibold text-rose-100">{text.title}</h2>
      <p className="mt-2 text-sm text-rose-100">{error.message}</p>
      {error.detail ? <p className="mt-1 text-xs text-rose-200/80">{text.detail}: {error.detail}</p> : null}
      <p className="mt-1 text-xs text-rose-200/80">{text.code}: {error.code}</p>

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={onRetry}
          disabled={busy || !error.retryable}
          className="rounded-md border border-rose-500 px-3 py-2 text-sm text-rose-100 hover:bg-rose-900/40 disabled:opacity-50"
        >
          {text.retry}
        </button>
        <button
          type="button"
          onClick={onEditInputs}
          disabled={busy}
          className="rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50"
        >
          {text.edit}
        </button>
        <button
          type="button"
          onClick={onOpenSettings}
          disabled={busy}
          className="rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50"
        >
          {text.settings}
        </button>
        <button
          type="button"
          onClick={onOpenLogs}
          disabled={busy}
          className="rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50"
        >
          {text.logs}
        </button>
        <button
          type="button"
          onClick={onBackToDashboard}
          disabled={busy}
          className="sm:col-span-2 rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50"
        >
          {text.back}
        </button>
      </div>
    </section>
  );
}
