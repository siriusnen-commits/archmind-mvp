# archmind-mvp

## Quick usage

### Generate a fullstack-ddd project
```bash
archmind generate --idea "defect tracker" --template fullstack-ddd --out generated --name hello_fullstack
```

### Pipeline (generate -> run -> fix -> run)
```bash
archmind pipeline --idea "defect tracker" --template fullstack-ddd --all --apply
```

### Run a generated project
```bash
# backend
cd generated/hello_fullstack
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# frontend (in another terminal)
cd generated/hello_fullstack/frontend
npm install
npm run dev
```

## 개발 설치
python -m pip install -e ".[dev]"
python -m pytest -q
