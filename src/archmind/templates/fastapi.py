# src/archmind/templates/fastapi.py
from __future__ import annotations
from typing import Dict

def enforce_fastapi_runtime(files: Dict[str, str], project_name: str) -> Dict[str, str]:
    # Always enforce runtime-critical files for reliability
    files["requirements.txt"] = (
        "fastapi==0.115.0\n"
        "uvicorn[standard]==0.30.6\n"
    )

    files["main.py"] = (
        "import os\n"
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/')\n"
        "def health():\n"
        "    return {'status': 'ok'}\n\n"
        "if __name__ == '__main__':\n"
        "    import uvicorn\n"
        "    host = os.getenv('HOST', '0.0.0.0')\n"
        "    port = int(os.getenv('PORT', '8000'))\n"
        "    uvicorn.run('main:app', host=host, port=port, reload=True)\n"
    )

    if not files.get("README.md", "").strip():
        files["README.md"] = (
            f"# {project_name}\n\n"
            "## Setup\n"
            "```bash\n"
            "python3 -m venv .venv\n"
            "source .venv/bin/activate\n"
            "python -m pip install -r requirements.txt\n"
            "```\n\n"
            "## Run\n"
            "```bash\n"
            "PORT=8000 python main.py\n"
            "```\n\n"
            "## Test\n"
            "```bash\n"
            "curl -s http://localhost:8000/\n"
            "```\n"
        )

    return files