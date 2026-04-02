"use client";

import type { CreateProjectStage } from "@/types/project-create";
import type { NewProjectLocaleTexts } from "@/components/new-project/locale";

const STAGES: CreateProjectStage[] = [
  "idle",
  "validating",
  "checking-runtime",
  "resolving-template",
  "generating",
  "initializing",
  "completed",
  "failed",
];

type Props = {
  stage: CreateProjectStage;
  locale: NewProjectLocaleTexts;
};

export default function CreateProjectStatusCard({ stage, locale }: Props) {
  const activeIndex = STAGES.indexOf(stage);

  return (
    <section className="rounded-lg border border-slate-700 bg-slate-900/70 p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">{locale.status.title}</h2>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {STAGES.map((item, index) => {
          const done = activeIndex > -1 && index < activeIndex;
          const active = item === stage;
          return (
            <li
              key={item}
              className={`rounded-md border px-3 py-2 text-xs ${
                active
                  ? "border-cyan-600 bg-cyan-500/10 text-cyan-100"
                  : done
                    ? "border-emerald-700 bg-emerald-500/10 text-emerald-100"
                    : "border-slate-700 bg-slate-950 text-slate-300"
              }`}
            >
              {locale.status.stages[item]}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
