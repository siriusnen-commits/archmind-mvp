"use client";

import type { CreateProjectError } from "@/types/project-create";

type Props = {
  error: CreateProjectError;
  onRetry: () => void;
  onEditInputs: () => void;
  onOpenSettings: () => void;
  onOpenLogs: () => void;
  onBackToDashboard: () => void;
  busy?: boolean;
};

export default function CreateProjectErrorCard({
  error,
  onRetry,
  onEditInputs,
  onOpenSettings,
  onOpenLogs,
  onBackToDashboard,
  busy = false,
}: Props) {
  return (
    <section className="rounded-lg border border-rose-700 bg-rose-950/40 p-4">
      <h2 className="text-sm font-semibold text-rose-100">생성 실패</h2>
      <p className="mt-2 text-sm text-rose-100">{error.message}</p>
      {error.detail ? <p className="mt-1 text-xs text-rose-200/80">상세: {error.detail}</p> : null}
      <p className="mt-1 text-xs text-rose-200/80">오류 코드: {error.code}</p>

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={onRetry}
          disabled={busy || !error.retryable}
          className="rounded-md border border-rose-500 px-3 py-2 text-sm text-rose-100 hover:bg-rose-900/40 disabled:opacity-50"
        >
          Retry
        </button>
        <button
          type="button"
          onClick={onEditInputs}
          disabled={busy}
          className="rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50"
        >
          Edit inputs
        </button>
        <button
          type="button"
          onClick={onOpenSettings}
          disabled={busy}
          className="rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50"
        >
          Open settings
        </button>
        <button
          type="button"
          onClick={onOpenLogs}
          disabled={busy}
          className="rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50"
        >
          Open logs
        </button>
        <button
          type="button"
          onClick={onBackToDashboard}
          disabled={busy}
          className="sm:col-span-2 rounded-md border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50"
        >
          Back to dashboard
        </button>
      </div>
    </section>
  );
}
