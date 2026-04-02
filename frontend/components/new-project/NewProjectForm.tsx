"use client";

import type { FormEvent } from "react";

import type { NewProjectLocaleTexts } from "@/components/new-project/locale";
import type { CreateProjectFormValues } from "@/types/project-create";
import type { GenerationMode, LlmMode, ProjectLanguage, TemplateOption } from "@/types/settings";

type Props = {
  values: CreateProjectFormValues;
  onChange: (next: CreateProjectFormValues) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  disabled?: boolean;
  locale: NewProjectLocaleTexts;
};

export default function NewProjectForm({ values, onChange, onSubmit, disabled = false, locale }: Props) {
  const text = locale.form;
  return (
    <form onSubmit={onSubmit} className="space-y-3 rounded-lg border border-slate-700 bg-slate-900/70 p-4 sm:p-5">
      <label className="block space-y-1">
        <span className="text-xs text-slate-300">{text.idea}</span>
        <textarea
          required
          value={values.idea}
          onChange={(event) => onChange({ ...values, idea: event.target.value })}
          placeholder={text.ideaPlaceholder}
          rows={4}
          disabled={disabled}
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
        />
      </label>

      <label className="block space-y-1">
        <span className="text-xs text-slate-300">{text.template}</span>
        <select
          value={values.template}
          onChange={(event) => onChange({ ...values, template: event.target.value as TemplateOption })}
          disabled={disabled}
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
        >
          <option value="auto">{text.templateOptions.auto}</option>
          <option value="diary">{text.templateOptions.diary}</option>
          <option value="todo">{text.templateOptions.todo}</option>
          <option value="kanban">{text.templateOptions.kanban}</option>
          <option value="bookmark">{text.templateOptions.bookmark}</option>
        </select>
      </label>

      <label className="block space-y-1">
        <span className="text-xs text-slate-300">{text.mode}</span>
        <select
          value={values.mode}
          onChange={(event) => onChange({ ...values, mode: event.target.value as GenerationMode })}
          disabled={disabled}
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
        >
          <option value="fast">{text.modeOptions.fast}</option>
          <option value="balanced">{text.modeOptions.balanced}</option>
          <option value="high_quality">{text.modeOptions.highQuality}</option>
        </select>
      </label>

      <label className="block space-y-1">
        <span className="text-xs text-slate-300">{text.language}</span>
        <select
          value={values.language}
          onChange={(event) => onChange({ ...values, language: event.target.value as ProjectLanguage })}
          disabled={disabled}
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
        >
          <option value="english">{text.languageOptions.english}</option>
          <option value="korean">{text.languageOptions.korean}</option>
          <option value="japanese">{text.languageOptions.japanese}</option>
        </select>
      </label>

      <label className="block space-y-1">
        <span className="text-xs text-slate-300">{text.llm}</span>
        <select
          value={values.llmMode}
          onChange={(event) => onChange({ ...values, llmMode: event.target.value as LlmMode })}
          disabled={disabled}
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
        >
          <option value="local">{text.llmOptions.local}</option>
          <option value="cloud">{text.llmOptions.cloud}</option>
          <option value="hybrid">{text.llmOptions.hybrid}</option>
        </select>
      </label>

      <button
        type="submit"
        disabled={disabled}
        className="w-full rounded-md border border-emerald-600 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-60"
      >
        {disabled ? text.submitBusy : text.submitIdle}
      </button>
    </form>
  );
}
