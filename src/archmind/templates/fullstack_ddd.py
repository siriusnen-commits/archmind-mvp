# src/archmind/templates/fullstack_ddd.py
from __future__ import annotations

from typing import Dict


def enforce_fullstack_ddd(_: Dict[str, str], project_name: str) -> Dict[str, str]:
    """
    Deterministic Fullstack DDD template.
    - Backend: FastAPI + SQLModel (DDD-ish)
    - Frontend: Next.js(App Router) + TS + Tailwind
    - Always runnable/testable skeleton
    """
    files: Dict[str, str] = {}

    # -------------------------
    # Backend (same pins as fastapi-ddd)
    # -------------------------
    files["requirements.txt"] = (
        "fastapi==0.115.0\n"
        "uvicorn[standard]==0.30.6\n"
        "sqlmodel==0.0.21\n"
        "pydantic==2.8.2\n"
        "pydantic-settings==2.4.0\n"
        "pytest==9.0.2\n"
        "httpx==0.27.0\n"
    )

    files["pytest.ini"] = (
        "[pytest]\n"
        "testpaths = tests\n"
        "addopts = -q\n"
    )

    files[".env.example"] = (
        f"APP_NAME={project_name}\n"
        "APP_PORT=8000\n"
        "BACKEND_BASE_URL=http://127.0.0.1:8000\n"
        "DB_URL=sqlite:///./data/app.db\n"
        "CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000\n"
    )

    # packages
    for p in [
        "app/__init__.py",
        "app/api/__init__.py",
        "app/api/routers/__init__.py",
        "app/core/__init__.py",
        "app/db/__init__.py",
        "app/domain/__init__.py",
        "app/repositories/__init__.py",
        "app/services/__init__.py",
        "tests/__init__.py",
    ]:
        files[p] = ""

    files["app/core/settings.py"] = f"""from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "backend/.env"), extra="ignore")

    app_name: str = "{project_name}"
    app_port: int = 8000
    backend_base_url: str = "http://127.0.0.1:8000"
    db_url: str = "sqlite:///./data/app.db"
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"


settings = Settings()
"""

    files["app/db/session.py"] = """from __future__ import annotations

from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

from app.core.settings import settings


engine = create_engine(settings.db_url, echo=False)


def init_db() -> None:
    Path("./data").mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
"""

    files["app/domain/models.py"] = """from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Defect(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    defect_type: str
    note: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
"""

    files["app/repositories/defect_repo.py"] = """from __future__ import annotations

from typing import List, Optional, Tuple

from sqlmodel import Session, func, select

from app.domain.models import Defect


class DefectRepository:
    def create(self, session: Session, *, defect_type: str, note: str = "") -> Defect:
        obj = Defect(defect_type=defect_type, note=note)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj

    def get(self, session: Session, defect_id: int) -> Optional[Defect]:
        return session.get(Defect, defect_id)

    def list(
        self,
        session: Session,
        *,
        q: Optional[str] = None,
        defect_type: Optional[str] = None,
        sort: str = "id",
        order: str = "desc",
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[Defect], int]:
        conditions = []
        if q:
            like = f"%{q}%"
            conditions.append((Defect.note.ilike(like)) | (Defect.defect_type.ilike(like)))
        if defect_type:
            conditions.append(Defect.defect_type.ilike(f"%{defect_type}%"))

        query = select(Defect)
        count_query = select(func.count()).select_from(Defect)
        for cond in conditions:
            query = query.where(cond)
            count_query = count_query.where(cond)

        order_col = Defect.created_at if sort == "created_at" else Defect.id
        order_by = order_col.asc() if order == "asc" else order_col.desc()

        total = session.exec(count_query).one()
        items = list(session.exec(query.order_by(order_by).offset(offset).limit(limit)).all())
        return items, int(total)

    def update(
        self,
        session: Session,
        obj: Defect,
        *,
        defect_type: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Defect:
        if defect_type is not None:
            obj.defect_type = defect_type
        if note is not None:
            obj.note = note
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj

    def delete(self, session: Session, obj: Defect) -> None:
        session.delete(obj)
        session.commit()
"""

    files["app/services/defect_service.py"] = """from __future__ import annotations

from typing import List, Optional, Tuple

from sqlmodel import Session

from app.domain.models import Defect
from app.repositories.defect_repo import DefectRepository


class DefectService:
    def __init__(self, repo: DefectRepository | None = None) -> None:
        self.repo = repo or DefectRepository()

    def create(self, session: Session, *, defect_type: str, note: str = "") -> Defect:
        return self.repo.create(session, defect_type=defect_type, note=note)

    def get(self, session: Session, defect_id: int) -> Optional[Defect]:
        return self.repo.get(session, defect_id)

    def list(
        self,
        session: Session,
        *,
        q: Optional[str] = None,
        defect_type: Optional[str] = None,
        sort: str = "id",
        order: str = "desc",
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[Defect], int]:
        return self.repo.list(
            session,
            q=q,
            defect_type=defect_type,
            sort=sort,
            order=order,
            offset=offset,
            limit=limit,
        )

    def update(
        self,
        session: Session,
        obj: Defect,
        *,
        defect_type: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Defect:
        return self.repo.update(session, obj, defect_type=defect_type, note=note)

    def delete(self, session: Session, obj: Defect) -> None:
        return self.repo.delete(session, obj)
"""

    files["app/api/schemas.py"] = """from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class DefectCreate(BaseModel):
    defect_type: str
    note: str = ""


class DefectUpdate(BaseModel):
    defect_type: Optional[str] = None
    note: Optional[str] = None


class DefectRead(BaseModel):
    id: int
    defect_type: str
    note: str
    created_at: datetime


class DefectListResponse(BaseModel):
    items: List[DefectRead]
    total: int
    page: int
    page_size: int
"""

    files["app/api/routers/health.py"] = """from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}
"""

    files["app/api/routers/defects.py"] = """from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.schemas import DefectCreate, DefectListResponse, DefectRead, DefectUpdate
from app.db.session import get_session
from app.services.defect_service import DefectService

router = APIRouter(prefix="/defects", tags=["defects"])


def _session_dep() -> Session:
    return get_session()


@router.post("", response_model=DefectRead)
def create_defect(payload: DefectCreate, session: Session = Depends(_session_dep)):
    svc = DefectService()
    obj = svc.create(session, defect_type=payload.defect_type, note=payload.note)
    return DefectRead.model_validate(obj, from_attributes=True)


@router.get("", response_model=DefectListResponse)
def list_defects(
    session: Session = Depends(_session_dep),
    q: str | None = Query(default=None),
    defect_type: str | None = Query(default=None, description="Partial match on defect_type"),
    sort: str = Query(default="id", pattern="^(id|created_at)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    svc = DefectService()
    offset = (page - 1) * page_size
    items, total = svc.list(
        session,
        q=q,
        defect_type=defect_type,
        sort=sort,
        order=order,
        offset=offset,
        limit=page_size,
    )
    return DefectListResponse(
        items=[DefectRead.model_validate(x, from_attributes=True) for x in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.put("/{defect_id}", response_model=DefectRead)
def update_defect(
    defect_id: int,
    payload: DefectUpdate,
    session: Session = Depends(_session_dep),
):
    svc = DefectService()
    obj = svc.get(session, defect_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Defect not found")
    updated = svc.update(session, obj, defect_type=payload.defect_type, note=payload.note)
    return DefectRead.model_validate(updated, from_attributes=True)


@router.delete("/{defect_id}")
def delete_defect(defect_id: int, session: Session = Depends(_session_dep)):
    svc = DefectService()
    obj = svc.get(session, defect_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Defect not found")
    svc.delete(session, obj)
    return {"status": "deleted"}
"""

    files["app/api/router.py"] = """from fastapi import APIRouter

from app.api.routers.health import router as health_router
from app.api.routers.defects import router as defects_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(defects_router)
"""

    # lifespan (경고 제거)
    files["app/main.py"] = """from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.settings import settings
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
origins = [x.strip() for x in settings.cors_allow_origins.split(",") if x.strip()]
if not origins:
    origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
"""

    files["main.py"] = """import os
import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", os.getenv("PORT", "8000")))
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
"""

    files["tests/conftest.py"] = """import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
"""

    files["tests/test_health.py"] = """from fastapi.testclient import TestClient
from app.main import app


def test_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
"""

    files["tests/test_defects.py"] = """from fastapi.testclient import TestClient
from app.main import app
from app.db.session import engine
from sqlmodel import SQLModel
from pathlib import Path


def setup_function():
    Path("./data").mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def test_defects_crud_and_pagination():
    client = TestClient(app)
    for i in range(5):
        r = client.post("/defects", json={"defect_type": f"HDMI_{i}", "note": f"n{i}"})
        assert r.status_code == 200

    r = client.get("/defects", params={"page": 1, "page_size": 2})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2

    first_id = data["items"][0]["id"]
    r = client.put(f"/defects/{first_id}", json={"note": "updated"})
    assert r.status_code == 200
    assert r.json()["note"] == "updated"

    r = client.delete(f"/defects/{first_id}")
    assert r.status_code == 200

    r = client.get("/defects", params={"q": "updated"})
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_defects_query_and_sorting():
    client = TestClient(app)
    for dtype in ["HDMI_CEC", "HDMI_ARC", "USB_POWER"]:
        client.post("/defects", json={"defect_type": dtype, "note": f"note {dtype}"})

    # defect_type partial match
    r = client.get("/defects", params={"defect_type": "HDMI"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2

    # text search (q) across note/defect_type
    r = client.get("/defects", params={"q": "USB"})
    assert r.status_code == 200
    assert r.json()["total"] == 1

    # sort by id asc
    r = client.get("/defects", params={"sort": "id", "order": "asc"})
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert ids == sorted(ids)
"""

    # -------------------------
    # Frontend (Next.js App Router)
    # -------------------------
    files["frontend/.env.example"] = (
        "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000\n"
        "NEXT_PUBLIC_FRONTEND_PORT=3000\n"
    )

    files["frontend/package.json"] = f"""{{
  "name": "{project_name}-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {{
    "dev": "next dev -p 5173",
    "build": "next build",
    "start": "sh -c 'next start -p ${{PORT:-3000}}'",
    "lint": "next lint"
  }},
  "dependencies": {{
    "next": "15.1.6",
    "react": "19.0.0",
    "react-dom": "19.0.0"
  }},
  "devDependencies": {{
    "@types/node": "20.11.30",
    "@types/react": "19.0.8",
    "@types/react-dom": "19.0.3",
    "autoprefixer": "10.4.20",
    "postcss": "8.4.49",
    "tailwindcss": "3.4.17",
    "typescript": "5.6.3",
    "eslint": "9.18.0",
    "eslint-config-next": "15.1.6"
  }}
}}
"""

    files["frontend/tsconfig.json"] = """{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "types": ["node"]
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
"""

    files["frontend/next-env.d.ts"] = """/// <reference types="next" />
/// <reference types="next/image-types/global" />

// NOTE: This file should not be edited
"""

    files["frontend/next.config.mjs"] = """/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone"
};

export default nextConfig;
"""

    files["frontend/postcss.config.mjs"] = """export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
"""

    files["frontend/tailwind.config.ts"] = """import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
} satisfies Config;
"""

    files["frontend/app/globals.css"] = """@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  color-scheme: light;
}

body {
  margin: 0;
}
"""

    files["frontend/app/layout.tsx"] = (
        'import "./globals.css";\n\n'
        "export const metadata = {\n"
        f'  title: "{project_name}",\n'
        "};\n\n"
        "export default function RootLayout({ children }: { children: React.ReactNode }) {\n"
        "  return (\n"
        '    <html lang="en">\n'
        "      <body>\n"
        '        <div className="min-h-screen bg-slate-950 text-slate-100">\n'
        '          <header className="border-b border-slate-800 bg-slate-900/80">\n'
        '            <div className="mx-auto max-w-5xl px-4 py-5">\n'
        '              <div className="flex items-center justify-between">\n'
        "                <div>\n"
        f'                  <div className="text-lg font-semibold tracking-wide">{project_name}</div>\n'
        '                  <div className="text-xs text-slate-400">FastAPI + Next.js workspace</div>\n'
        "                </div>\n"
        '                <div className="text-xs text-slate-400">/ · /notes · /ui/defects</div>\n'
        "              </div>\n"
        "            </div>\n"
        "          </header>\n"
        '          <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>\n'
        "        </div>\n"
        "      </body>\n"
        "    </html>\n"
        "  );\n"
        "}\n"
    )

    files["frontend/app/page.tsx"] = """"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function Page() {
  const router = useRouter();
  const [checkingNotes, setCheckingNotes] = useState(true);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const response = await fetch("/notes", { cache: "no-store" });
        if (!active) return;
        if (response.ok) {
          router.replace("/notes");
          return;
        }
      } catch {
        // Ignore and show default landing.
      }
      if (active) {
        setCheckingNotes(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [router]);

  if (checkingNotes) {
    return <p className="text-sm text-slate-300">Loading workspace...</p>;
  }

  return (
    <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
      <h1 className="text-lg font-semibold">Project Home</h1>
      <p className="text-sm text-slate-300">
        Open the generated domain pages. If Note pages exist, this page will auto-open <code>/notes</code>.
      </p>
      <div className="flex flex-wrap gap-2 text-sm">
        <Link href="/notes" className="rounded-lg border border-slate-700 px-3 py-2 hover:bg-slate-800">
          Notes
        </Link>
        <Link href="/ui/defects" className="rounded-lg border border-slate-700 px-3 py-2 hover:bg-slate-800">
          Defects
        </Link>
      </div>
    </section>
  );
}
"""

    files["frontend/app/ui/defects/page.tsx"] = """import DefectsPage from "../../ui/DefectsPage";

export default function DefectsRoutePage() {
  return <DefectsPage />;
}
"""

    files["frontend/app/_lib/apiBase.ts"] = """"use client";

import { useEffect, useState } from "react";

const ENV_API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;
const ENV_BACKEND_PORT = process.env.NEXT_PUBLIC_BACKEND_PORT || "8000";
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

function isLoopbackHost(hostname: string) {
  return LOOPBACK_HOSTS.has((hostname || "").trim().toLowerCase());
}

function normalizeApiBase(raw: string): string {
  return String(raw || "").trim().replace(/\\/$/, "");
}

export function resolveRuntimeApiBaseUrl(): string {
  const fallbackPort = String(ENV_BACKEND_PORT || "8000").trim() || "8000";
  const loopbackFallback = `http://127.0.0.1:${fallbackPort}`;
  const hasWindow = typeof window !== "undefined";
  const browserHost = hasWindow ? (window.location.hostname || "").trim() : "";
  const browserProtocol = hasWindow && window.location.protocol === "https:" ? "https" : "http";
  if (ENV_API_BASE && ENV_API_BASE.trim()) {
    const rawEnvBase = ENV_API_BASE.trim();
    try {
      const parsed = new URL(rawEnvBase);
      if (!isLoopbackHost(parsed.hostname)) {
        return normalizeApiBase(parsed.toString());
      }
      if (!browserHost || isLoopbackHost(browserHost)) {
        return normalizeApiBase(parsed.toString());
      }
      parsed.hostname = browserHost;
      return normalizeApiBase(parsed.toString());
    } catch {
      return normalizeApiBase(rawEnvBase);
    }
  }
  if (browserHost) {
    return `${browserProtocol}://${browserHost}:${fallbackPort}`;
  }
  return loopbackFallback;
}

export function useResolvedApiBaseUrl(): string {
  const [apiBaseUrl, setApiBaseUrl] = useState<string>(() => resolveRuntimeApiBaseUrl());

  useEffect(() => {
    setApiBaseUrl(resolveRuntimeApiBaseUrl());
  }, []);

  return apiBaseUrl;
}
"""

    files["frontend/app/ui/DefectsPage.tsx"] = """"use client";

import { useEffect, useMemo, useState } from "react";
import { useResolvedApiBaseUrl } from "../_lib/apiBase";

type Defect = {
  id: number;
  defect_type: string;
  note: string;
  created_at: string;
};

type DefectListResponse = {
  items: Defect[];
  total: number;
  page: number;
  page_size: number;
};

export default function DefectsPage() {
  const apiBaseUrl = useResolvedApiBaseUrl();
  const [items, setItems] = useState<Defect[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [defectType, setDefectType] = useState("HDMI_CEC");
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<Defect | null>(null);

  const [q, setQ] = useState("");
  const [filterType, setFilterType] = useState("");
  const [sort, setSort] = useState<"id" | "created_at">("id");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);

  function humanizeError(err: unknown) {
    if (err instanceof TypeError) {
      return "Network/CORS error. Check backend URL and CORS settings.";
    }
    if (err instanceof Error) return err.message;
    return "Unknown error";
  }

  const api = useMemo(
    () => ({
      async list(params: {
        q?: string;
        defect_type?: string;
        sort?: string;
        order?: string;
        page?: number;
        page_size?: number;
      }) {
        const qs = new URLSearchParams();
        if (params.q) qs.set("q", params.q);
        if (params.defect_type) qs.set("defect_type", params.defect_type);
        if (params.sort) qs.set("sort", params.sort);
        if (params.order) qs.set("order", params.order);
        if (params.page) qs.set("page", String(params.page));
        if (params.page_size) qs.set("page_size", String(params.page_size));

        const r = await fetch(`${apiBaseUrl}/defects?${qs.toString()}`, { cache: "no-store" });
        if (!r.ok) throw new Error(`GET /defects failed: ${r.status}`);
        return (await r.json()) as DefectListResponse;
      },
      async create(payload: { defect_type: string; note: string }) {
        const r = await fetch(`${apiBaseUrl}/defects`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(`POST /defects failed: ${r.status}`);
        return (await r.json()) as Defect;
      },
      async update(id: number, payload: { defect_type?: string; note?: string }) {
        const r = await fetch(`${apiBaseUrl}/defects/${id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(`PUT /defects/${id} failed: ${r.status}`);
        return (await r.json()) as Defect;
      },
      async remove(id: number) {
        const r = await fetch(`${apiBaseUrl}/defects/${id}`, { method: "DELETE" });
        if (!r.ok) throw new Error(`DELETE /defects/${id} failed: ${r.status}`);
        return (await r.json()) as { status: string };
      },
    }),
    [apiBaseUrl]
  );

  async function refresh(nextPage = page) {
    setLoading(true);
    setError(null);
    try {
      const data = await api.list({
        q: q.trim() || undefined,
        defect_type: filterType.trim() || undefined,
        sort,
        order,
        page: nextPage,
        page_size: pageSize,
      });
      setItems(data.items);
      setTotal(data.total);
      setPage(data.page);
      setPageSize(data.page_size);
    } catch (err) {
      setError(humanizeError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh(1).catch(console.error);
  }, []);

  useEffect(() => {
    refresh(1).catch(console.error);
  }, [q, filterType, sort, order, pageSize]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!defectType.trim()) return;
    setLoading(true);
    setError(null);
    try {
      if (editing) {
        await api.update(editing.id, {
          defect_type: defectType.trim(),
          note: note.trim(),
        });
      } else {
        await api.create({ defect_type: defectType.trim(), note: note.trim() });
      }
      setNote("");
      setEditing(null);
      await refresh(1);
    } catch (err) {
      setError(humanizeError(err));
    } finally {
      setLoading(false);
    }
  }

  function beginEdit(item: Defect) {
    setEditing(item);
    setDefectType(item.defect_type);
    setNote(item.note);
  }

  function cancelEdit() {
    setEditing(null);
    setDefectType("HDMI_CEC");
    setNote("");
  }

  async function remove(item: Defect) {
    if (!confirm(`Delete defect #${item.id}?`)) return;
    setLoading(true);
    setError(null);
    try {
      await api.remove(item.id);
      await refresh(page);
    } catch (err) {
      setError(humanizeError(err));
    } finally {
      setLoading(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 shadow-lg">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Defect intake</h2>
            <p className="text-xs text-slate-400">Backend: {apiBaseUrl}</p>
          </div>
          <div className="text-xs text-slate-500">Total {total}</div>
        </div>

        <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-6">
          <div className="md:col-span-2">
            <label className="text-xs text-slate-400">defect_type</label>
            <input
              value={defectType}
              onChange={(e) => setDefectType(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              placeholder="HDMI_CEC"
            />
          </div>
          <div className="md:col-span-3">
            <label className="text-xs text-slate-400">note</label>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              placeholder="Explain the issue"
            />
          </div>
          <div className="md:col-span-1 flex items-end gap-2">
            <button
              type="submit"
              className="w-full rounded-lg bg-emerald-400 px-3 py-2 text-sm font-semibold text-emerald-950"
              disabled={loading}
            >
              {editing ? "Update" : "Add"}
            </button>
          </div>
          {editing && (
            <div className="md:col-span-6">
              <button
                type="button"
                onClick={cancelEdit}
                className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200"
              >
                Cancel edit
              </button>
            </div>
          )}
        </form>

        {error && <div className="mt-3 rounded-lg border border-rose-500/60 bg-rose-500/10 px-3 py-2 text-xs">{error}</div>}
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 shadow-lg">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">Defects</h2>
          <div className="text-xs text-slate-400">
            Page {page} / {totalPages}
          </div>
        </div>

        <div className="mb-4 grid gap-3 md:grid-cols-6">
          <div className="md:col-span-2">
            <label className="text-xs text-slate-400">Search</label>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              placeholder="type to search"
            />
          </div>
          <div className="md:col-span-2">
            <label className="text-xs text-slate-400">Filter defect_type</label>
            <input
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              placeholder="HDMI"
            />
          </div>
          <div className="md:col-span-1">
            <label className="text-xs text-slate-400">Sort</label>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as "id" | "created_at")}
              className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            >
              <option value="id">id</option>
              <option value="created_at">created_at</option>
            </select>
          </div>
          <div className="md:col-span-1">
            <label className="text-xs text-slate-400">Order</label>
            <select
              value={order}
              onChange={(e) => setOrder(e.target.value as "asc" | "desc")}
              className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            >
              <option value="desc">desc</option>
              <option value="asc">asc</option>
            </select>
          </div>
          <div className="md:col-span-1">
            <label className="text-xs text-slate-400">Page size</label>
            <select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            >
              {[5, 10, 20, 50].map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-400">
              <tr>
                <th className="py-2">ID</th>
                <th>Type</th>
                <th>Note</th>
                <th>Created</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((x) => (
                <tr key={x.id} className="border-t border-slate-800/70">
                  <td className="py-2">{x.id}</td>
                  <td className="font-mono text-emerald-300">{x.defect_type}</td>
                  <td>{x.note}</td>
                  <td className="text-xs text-slate-500">{new Date(x.created_at).toLocaleString()}</td>
                  <td className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => beginEdit(x)}
                        className="rounded-md border border-slate-700 px-2 py-1 text-xs"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(x)}
                        className="rounded-md border border-rose-500/60 px-2 py-1 text-xs text-rose-300"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-slate-500">
                    {loading ? "Loading..." : "No defects yet."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400">
          <div>
            Showing {items.length} of {total}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => refresh(Math.max(1, page - 1))}
              disabled={page <= 1 || loading}
              className="rounded-md border border-slate-700 px-2 py-1"
            >
              Prev
            </button>
            <button
              type="button"
              onClick={() => refresh(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages || loading}
              className="rounded-md border border-slate-700 px-2 py-1"
            >
              Next
            </button>
            <button
              type="button"
              onClick={() => refresh(page)}
              disabled={loading}
              className="rounded-md border border-slate-700 px-2 py-1"
            >
              Refresh
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
"""

    # Root helper scripts (선택)
    files["scripts/dev_backend.sh"] = """#!/usr/bin/env bash
set -euo pipefail
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port ${APP_PORT:-${PORT:-8000}}
"""
    files["scripts/dev_frontend.sh"] = """#!/usr/bin/env bash
set -euo pipefail
cd frontend
npm install
cp -n .env.example .env.local || true
npm run dev
"""

    files["README.md"] = f"""# {project_name}

## Backend setup
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Backend run
```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port ${{APP_PORT:-${{PORT:-8000}}}}
```

## Frontend setup
```bash
cd frontend
npm install
cp -n .env.example .env.local
```

## Frontend run
```bash
npm run dev
```

## Tests
```bash
python -m pytest -q
```

## Environment
- `APP_NAME` (default: {project_name})
- `APP_PORT` (default: 8000)
- `BACKEND_BASE_URL` (default: http://127.0.0.1:8000)
- `DB_URL` (default: sqlite:///./data/app.db)
- `CORS_ALLOW_ORIGINS` (comma-separated frontend origins)
- `NEXT_PUBLIC_API_BASE_URL` (frontend -> backend base URL)
- `NEXT_PUBLIC_FRONTEND_PORT` (frontend runtime port)
"""

    backend_prefixed: Dict[str, str] = {}
    for path, content in files.items():
        if path.startswith(("frontend/", "scripts/")) or path == "README.md":
            backend_prefixed[path] = content
            continue
        backend_prefixed[f"backend/{path}"] = content

    # Fullstack contract: no root launcher; runtime starts backend/app/main.py via cwd=backend.
    backend_prefixed.pop("backend/main.py", None)

    backend_prefixed["scripts/dev_backend.sh"] = """#!/usr/bin/env bash
set -euo pipefail
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port ${APP_PORT:-${PORT:-8000}}
"""
    backend_prefixed["README.md"] = f"""# {project_name}

## Backend setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Backend run
```bash
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port ${{APP_PORT:-${{PORT:-8000}}}}
```

## Frontend setup
```bash
cd frontend
npm install
cp -n .env.example .env.local
```

## Frontend run
```bash
npm run dev
```

## Tests
```bash
cd backend
python -m pytest -q
```

## Environment
- `APP_NAME` (default: {project_name})
- `APP_PORT` (default: 8000)
- `BACKEND_BASE_URL` (default: http://127.0.0.1:8000)
- `DB_URL` (default: sqlite:///./data/app.db)
- `CORS_ALLOW_ORIGINS` (comma-separated frontend origins)
- `NEXT_PUBLIC_API_BASE_URL` (frontend -> backend base URL)
- `NEXT_PUBLIC_FRONTEND_PORT` (frontend runtime port)
"""

    return backend_prefixed
