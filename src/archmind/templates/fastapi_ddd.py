# src/archmind/templates/fastapi_ddd.py
from __future__ import annotations
from typing import Dict


def enforce_fastapi_ddd(files: Dict[str, str], project_name: str) -> Dict[str, str]:
    """
    Deterministic, high-quality FastAPI template (DDD-ish layering):
      - app/main.py with startup DB init
      - routers separated
      - domain models (SQLModel)
      - repository + service layers
      - settings via pydantic-settings (.env)
      - pytest health test
    """
    # For "final quality", we expect caller to pass {} to avoid model noise.
    # But even if something is passed, we overwrite runtime-critical files deterministically.
    files["app/__init__.py"] = ""

    files["pytest.ini"] = (
    "[pytest]\n"
    "testpaths = tests\n"
    "pythonpath = .\n"
    )

    # Make packages explicit (prevents import issues as project grows)
    files["app/__init__.py"] = ""
    files["app/api/__init__.py"] = ""
    files["app/core/__init__.py"] = ""
    files["app/db/__init__.py"] = ""
    files["app/domain/__init__.py"] = ""
    files["app/repositories/__init__.py"] = ""
    files["app/services/__init__.py"] = ""
    files["requirements.txt"] = (
        "fastapi==0.115.0\n"
        "uvicorn[standard]==0.30.6\n"
        "sqlmodel==0.0.21\n"
        "pydantic==2.8.2\n"
        "pydantic-settings==2.4.0\n"
        "pytest==8.3.2\n"
        "httpx==0.27.0\n"
    )
        # Make packages explicit (stable imports for pytest/runtime)
    files["app/__init__.py"] = ""
    files["app/api/__init__.py"] = ""
    files["app/core/__init__.py"] = ""
    files["app/db/__init__.py"] = ""
    files["app/domain/__init__.py"] = ""
    files["app/repositories/__init__.py"] = ""
    files["app/services/__init__.py"] = ""

    # Ensure pytest can import from project root without PYTHONPATH hacks
    files["pytest.ini"] = (
        "[pytest]\n"
        "testpaths = tests\n"
        "pythonpath = .\n"
    )
        # Make packages explicit (stable imports for pytest/runtime)
    files["app/__init__.py"] = ""
    files["app/api/__init__.py"] = ""
    files["app/core/__init__.py"] = ""
    files["app/db/__init__.py"] = ""
    files["app/domain/__init__.py"] = ""
    files["app/repositories/__init__.py"] = ""
    files["app/services/__init__.py"] = ""

    # Ensure pytest can import from project root without PYTHONPATH hacks
    files["pytest.ini"] = (
        "[pytest]\n"
        "testpaths = tests\n"
        "pythonpath = .\n"
    )

    # .env example
    files[".env.example"] = (
        "DATABASE_URL=sqlite:///./app.db\n"
        "ENV=dev\n"
        "LOG_LEVEL=INFO\n"
    )

    # core config
    files["app/core/config.py"] = (
        "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n"
        "class Settings(BaseSettings):\n"
        "    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')\n"
        "    database_url: str = 'sqlite:///./app.db'\n"
        "    env: str = 'dev'\n"
        "    log_level: str = 'INFO'\n\n"
        "settings = Settings()\n"
    )

    # db session + init
    files["app/db/session.py"] = (
        "from sqlmodel import Session, create_engine\n"
        "from app.core.config import settings\n\n"
        "engine = create_engine(settings.database_url, echo=False)\n\n"
        "def get_session():\n"
        "    return Session(engine)\n"
    )

    files["app/db/base.py"] = (
        "from sqlmodel import SQLModel\n"
        "from app.db.session import engine\n\n"
        "def init_db():\n"
        "    SQLModel.metadata.create_all(engine)\n"
    )

    # domain model
    files["app/domain/models.py"] = (
        "from sqlmodel import SQLModel, Field\n\n"
        "class Defect(SQLModel, table=True):\n"
        "    id: int | None = Field(default=None, primary_key=True)\n"
        "    defect_type: str\n"
        "    description: str | None = None\n"
    )

    # schemas
    files["app/schemas.py"] = (
        "from sqlmodel import SQLModel\n\n"
        "class DefectCreate(SQLModel):\n"
        "    defect_type: str\n"
        "    description: str | None = None\n\n"
        "class DefectRead(SQLModel):\n"
        "    id: int\n"
        "    defect_type: str\n"
        "    description: str | None = None\n"
    )

    # repository
    files["app/repositories/defect_repo.py"] = (
        "from typing import List\n"
        "from sqlmodel import select\n"
        "from app.db.session import get_session\n"
        "from app.domain.models import Defect\n\n"
        "def insert_defect(defect: Defect) -> Defect:\n"
        "    with get_session() as session:\n"
        "        session.add(defect)\n"
        "        session.commit()\n"
        "        session.refresh(defect)\n"
        "        return defect\n\n"
        "def list_all_defects() -> List[Defect]:\n"
        "    with get_session() as session:\n"
        "        return list(session.exec(select(Defect)).all())\n"
    )

    # service
    files["app/services/defect_service.py"] = (
        "from app.domain.models import Defect\n"
        "from app.schemas import DefectCreate, DefectRead\n"
        "from app.repositories.defect_repo import insert_defect, list_all_defects\n\n"
        "def create_defect(payload: DefectCreate) -> DefectRead:\n"
        "    d = Defect(defect_type=payload.defect_type, description=payload.description)\n"
        "    saved = insert_defect(d)\n"
        "    return DefectRead(id=saved.id or 0, defect_type=saved.defect_type, description=saved.description)\n\n"
        "def list_defects() -> list[DefectRead]:\n"
        "    items = list_all_defects()\n"
        "    return [DefectRead(id=i.id or 0, defect_type=i.defect_type, description=i.description) for i in items]\n"
    )

    # routers
    files["app/api/routers/health.py"] = (
        "from fastapi import APIRouter\n\n"
        "router = APIRouter(tags=['health'])\n\n"
        "@router.get('/health')\n"
        "def health():\n"
        "    return {'status': 'ok'}\n"
    )

    files["app/api/routers/defects.py"] = (
        "from fastapi import APIRouter\n"
        "from app.schemas import DefectCreate, DefectRead\n"
        "from app.services.defect_service import create_defect, list_defects\n\n"
        "router = APIRouter(prefix='/defects', tags=['defects'])\n\n"
        "@router.post('', response_model=DefectRead)\n"
        "def create(payload: DefectCreate):\n"
        "    return create_defect(payload)\n\n"
        "@router.get('', response_model=list[DefectRead])\n"
        "def list_all():\n"
        "    return list_defects()\n"
    )

    files["app/api/routers/__init__.py"] = (
        "from . import health, defects\n"
    )

    # app main
    files["app/main.py"] = (
        "from contextlib import asynccontextmanager\n"
        "from fastapi import FastAPI\n"
        "from app.api.routers import health, defects\n"
        "from app.db.base import init_db\n\n"
        "@asynccontextmanager\n"
        "async def lifespan(app: FastAPI):\n"
        "    init_db()\n"
        "    yield\n\n"
        "app = FastAPI(title='ArchMind Generated API', lifespan=lifespan)\n"
        "app.include_router(health.router)\n"
        "app.include_router(defects.router)\n\n"
        "@app.get('/')\n"
        "def root():\n"
        "    return {'status': 'ok'}\n"
    )

    # tests
    files["tests/test_health.py"] = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n\n"
        "client = TestClient(app)\n\n"
        "def test_health():\n"
        "    r = client.get('/health')\n"
        "    assert r.status_code == 200\n"
        "    assert r.json()['status'] == 'ok'\n"
    )

    # README
    files["README.md"] = (
        f"# {project_name}\n\n"
        "## Setup\n"
        "```bash\n"
        "python3 -m venv .venv\n"
        "source .venv/bin/activate\n"
        "python -m pip install -r requirements.txt\n"
        "cp .env.example .env\n"
        "```\n\n"
        "## Run\n"
        "```bash\n"
        "uvicorn app.main:app --reload --port 8000\n"
        "```\n\n"
        "## Test\n"
        "```bash\n"
        "pytest -q\n"
        "```\n\n"
        "## Endpoints\n"
        "- GET /health\n"
        "- POST /defects\n"
        "- GET /defects\n"
    )

    return files