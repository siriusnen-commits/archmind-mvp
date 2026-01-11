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

from typing import List

from sqlmodel import Session, select

from app.domain.models import Defect


class DefectRepository:
    def create(self, session: Session, *, defect_type: str, note: str = "") -> Defect:
        obj = Defect(defect_type=defect_type, note=note)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj

    def list(self, session: Session) -> List[Defect]:
        return list(session.exec(select(Defect).order_by(Defect.id.desc())).all())
"""

    files["app/services/defect_service.py"] = """from __future__ import annotations

from typing import List

from sqlmodel import Session

from app.domain.models import Defect
from app.repositories.defect_repo import DefectRepository


class DefectService:
    def __init__(self, repo: DefectRepository | None = None) -> None:
        self.repo = repo or DefectRepository()

    def create(self, session: Session, *, defect_type: str, note: str = "") -> Defect:
        return self.repo.create(session, defect_type=defect_type, note=note)

    def list(self, session: Session) -> List[Defect]:
        return self.repo.list(session)
"""

    files["app/api/schemas.py"] = """from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class DefectCreate(BaseModel):
    defect_type: str
    note: str = ""


class DefectRead(BaseModel):
    id: int
    defect_type: str
    note: str
    created_at: datetime
"""

    files["app/api/routers/health.py"] = """from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}
"""

    files["app/api/routers/defects.py"] = """from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.schemas import DefectCreate, DefectRead
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


@router.get("", response_model=list[DefectRead])
def list_defects(session: Session = Depends(_session_dep)):
    svc = DefectService()
    items = svc.list(session)
    return [DefectRead.model_validate(x, from_attributes=True) for x in items]
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

from app.api.router import api_router
from app.core.config import settings
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
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

    # README는 지금 단계에선 없어도 됨 (중요한 건 requirements/pytest/tests)
    return files
