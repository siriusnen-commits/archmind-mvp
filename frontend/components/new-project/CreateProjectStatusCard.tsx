"use client";

import type { CreateProjectStage } from "@/types/project-create";
import type { UiLanguage } from "@/types/settings";

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

const LABEL_BY_STAGE: Record<CreateProjectStage, string> = {
  idle: "대기 중",
  validating: "입력 검증",
  "checking-runtime": "런타임 점검",
  "resolving-template": "템플릿 확인",
  generating: "생성 실행",
  initializing: "프로젝트 초기화",
  completed: "완료",
  failed: "실패",
};

type Props = {
  stage: CreateProjectStage;
  uiLanguage?: UiLanguage;
};

export default function CreateProjectStatusCard({ stage, uiLanguage = "en" }: Props) {
  const activeIndex = STAGES.indexOf(stage);
  const title = uiLanguage === "ko" ? "생성 진행 상태" : uiLanguage === "ja" ? "生成ステータス" : "Generation Status";

  return (
    <section className="rounded-lg border border-slate-700 bg-slate-900/70 p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">{title}</h2>
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
              {LABEL_BY_STAGE[item]}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
