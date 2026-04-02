import type { CreateProjectStage } from "@/types/project-create";
import type { UiLanguage } from "@/types/settings";

export type NewProjectLocaleTexts = {
  page: {
    title: string;
    description: string;
    back: string;
    invalidIdea: string;
  };
  status: {
    title: string;
    stages: Record<CreateProjectStage, string>;
  };
  form: {
    idea: string;
    ideaPlaceholder: string;
    template: string;
    templateOptions: {
      auto: string;
      diary: string;
      todo: string;
      kanban: string;
      bookmark: string;
    };
    mode: string;
    modeOptions: {
      fast: string;
      balanced: string;
      highQuality: string;
    };
    language: string;
    languageOptions: {
      english: string;
      korean: string;
      japanese: string;
    };
    llm: string;
    llmOptions: {
      local: string;
      cloud: string;
      hybrid: string;
    };
    submitIdle: string;
    submitBusy: string;
  };
  error: {
    title: string;
    detail: string;
    code: string;
    retry: string;
    edit: string;
    settings: string;
    logs: string;
    back: string;
  };
};

const EN: NewProjectLocaleTexts = {
  page: {
    title: "New Project",
    description: "Create a project from your idea.",
    back: "Back",
    invalidIdea: "Please enter an idea.",
  },
  status: {
    title: "Generation Status",
    stages: {
      idle: "Idle",
      validating: "Validating Input",
      "checking-runtime": "Checking Runtime",
      "resolving-template": "Resolving Template",
      generating: "Generating",
      initializing: "Initializing Project",
      completed: "Completed",
      failed: "Failed",
    },
  },
  form: {
    idea: "Idea",
    ideaPlaceholder: "personal diary app\ntodo app with deadlines\nbookmark manager with tags",
    template: "Template",
    templateOptions: {
      auto: "Auto",
      diary: "Diary",
      todo: "Todo",
      kanban: "Kanban",
      bookmark: "Bookmark",
    },
    mode: "Generation Mode",
    modeOptions: {
      fast: "Fast",
      balanced: "Balanced",
      highQuality: "High Quality",
    },
    language: "Project Language",
    languageOptions: {
      english: "English",
      korean: "Korean",
      japanese: "Japanese",
    },
    llm: "LLM Mode",
    llmOptions: {
      local: "Local",
      cloud: "Cloud",
      hybrid: "Hybrid",
    },
    submitIdle: "Generate Project",
    submitBusy: "Generating...",
  },
  error: {
    title: "Creation Failed",
    detail: "Detail",
    code: "Error Code",
    retry: "Retry",
    edit: "Edit inputs",
    settings: "Open settings",
    logs: "Open logs",
    back: "Back to dashboard",
  },
};

const KO: NewProjectLocaleTexts = {
  page: {
    title: "새 프로젝트",
    description: "아이디어 기반 프로젝트 생성을 시작합니다.",
    back: "뒤로",
    invalidIdea: "아이디어를 입력해 주세요.",
  },
  status: {
    title: "생성 진행 상태",
    stages: {
      idle: "대기 중",
      validating: "입력 검증",
      "checking-runtime": "런타임 점검",
      "resolving-template": "템플릿 확인",
      generating: "생성 실행",
      initializing: "프로젝트 초기화",
      completed: "완료",
      failed: "실패",
    },
  },
  form: {
    idea: "아이디어",
    ideaPlaceholder: "개인 다이어리 앱\n마감일이 있는 할 일 앱\n태그가 있는 북마크 관리 앱",
    template: "템플릿",
    templateOptions: {
      auto: "자동",
      diary: "다이어리",
      todo: "할 일",
      kanban: "칸반",
      bookmark: "북마크",
    },
    mode: "생성 모드",
    modeOptions: {
      fast: "빠름",
      balanced: "균형",
      highQuality: "고품질",
    },
    language: "프로젝트 언어",
    languageOptions: {
      english: "영어",
      korean: "한국어",
      japanese: "일본어",
    },
    llm: "LLM 모드",
    llmOptions: {
      local: "로컬",
      cloud: "클라우드",
      hybrid: "하이브리드",
    },
    submitIdle: "프로젝트 생성",
    submitBusy: "생성 중...",
  },
  error: {
    title: "생성 실패",
    detail: "상세",
    code: "오류 코드",
    retry: "재시도",
    edit: "입력 수정",
    settings: "설정 열기",
    logs: "로그 보기",
    back: "대시보드로 돌아가기",
  },
};

const JA: NewProjectLocaleTexts = {
  page: {
    title: "新しいプロジェクト",
    description: "アイデアから新規プロジェクトを生成します。",
    back: "戻る",
    invalidIdea: "アイデアを入力してください。",
  },
  status: {
    title: "生成ステータス",
    stages: {
      idle: "待機中",
      validating: "入力検証",
      "checking-runtime": "ランタイム確認",
      "resolving-template": "テンプレート確認",
      generating: "生成実行",
      initializing: "プロジェクト初期化",
      completed: "完了",
      failed: "失敗",
    },
  },
  form: {
    idea: "アイデア",
    ideaPlaceholder: "個人日記アプリ\n期限付きToDoアプリ\nタグ付きブックマーク管理アプリ",
    template: "テンプレート",
    templateOptions: {
      auto: "自動",
      diary: "日記",
      todo: "ToDo",
      kanban: "カンバン",
      bookmark: "ブックマーク",
    },
    mode: "生成モード",
    modeOptions: {
      fast: "高速",
      balanced: "バランス",
      highQuality: "高品質",
    },
    language: "プロジェクト言語",
    languageOptions: {
      english: "英語",
      korean: "韓国語",
      japanese: "日本語",
    },
    llm: "LLMモード",
    llmOptions: {
      local: "ローカル",
      cloud: "クラウド",
      hybrid: "ハイブリッド",
    },
    submitIdle: "プロジェクト生成",
    submitBusy: "生成中...",
  },
  error: {
    title: "生成失敗",
    detail: "詳細",
    code: "エラーコード",
    retry: "再試行",
    edit: "入力を編集",
    settings: "設定を開く",
    logs: "ログを開く",
    back: "ダッシュボードへ戻る",
  },
};

export const NEW_PROJECT_LOCALES: Record<UiLanguage, NewProjectLocaleTexts> = {
  en: EN,
  ko: KO,
  ja: JA,
};

export function getNewProjectLocale(uiLanguage: UiLanguage): NewProjectLocaleTexts {
  return NEW_PROJECT_LOCALES[uiLanguage] || EN;
}
