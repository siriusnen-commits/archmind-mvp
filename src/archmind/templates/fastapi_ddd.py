from __future__ import annotations

from typing import Dict


def enforce_fastapi_ddd(_: Dict[str, str], project_name: str) -> Dict[str, str]:
    """
    Deterministic FastAPI DDD-ish template.
    - Model output is ignored completely.
    - Always generates a runnable + testable skeleton.
    """
    files: Dict[str, str] = {}

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
        "DB_URL=sqlite:///./data/app.db\n"
        "ALLOW_ORIGINS=*\n"
    )

    # packages
    files["app/__init__.py"] = ""
    files["app/api/__init__.py"] = ""
    files["app/api/routers/__init__.py"] = ""
    files["app/core/__init__.py"] = ""
    files["app/db/__init__.py"] = ""
    files["app/domain/__init__.py"] = ""
    files["app/repositories/__init__.py"] = ""
    files["app/services/__init__.py"] = ""
    files["tests/__init__.py"] = ""

    files["app/core/config.py"] = f"""from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "{project_name}"
    db_url: str = "sqlite:///./data/app.db"
    allow_origins: str = "*"


settings = Settings()
"""

    files["app/db/session.py"] = """from __future__ import annotations

from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

from app.core.config import settings


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
            conditions.append(Defect.defect_type == defect_type)

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
    defect_type: str | None = Query(default=None),
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

    files["app/main.py"] = """from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
origins = [x.strip() for x in settings.allow_origins.split(",") if x.strip()]
if not origins:
    origins = ["*"]
if origins == ["*"]:
    allow_origins = ["*"]
else:
    allow_origins = origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
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
    port = int(os.getenv("PORT", "8000"))
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


def setup_function():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def test_defects_crud_and_pagination():
    client = TestClient(app)
    for i in range(5):
        r = client.post("/defects", json={"defect_type": "HDMI", "note": f"n{i}"})
        assert r.status_code == 200

    r = client.get("/defects", params={"page": 1, "page_size": 2})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2

    first_id = data["items"][0]["id"]
    r = client.put(f"/defects/{first_id}", json={"note": "updated"})
    assert r.status_code == 200
    assert r.json()["note"] == "updated"

    r = client.delete(f"/defects/{first_id}")
    assert r.status_code == 200

    r = client.get("/defects", params={"q": "updated"})
    assert r.status_code == 200
    assert r.json()["total"] == 0
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
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Tests
```bash
python -m pytest -q
```

## Environment
- `APP_NAME` (default: {project_name})
- `DB_URL` (default: sqlite:///./data/app.db)
- `ALLOW_ORIGINS` (default: *)
"""
    return files
