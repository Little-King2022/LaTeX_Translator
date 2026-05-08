# LaTeX LLM Translator

MVP for translating English LaTeX paper projects into Chinese at source level.

## Run Locally

Backend requires Python 3.10+:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. Default login is `admin` / `admin` unless overridden by `.env`.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

## MVP Scope

- Single-user JWT login.
- OpenAI-compatible `/v1/chat/completions` LLM configuration and connection test.
- LaTeX zip upload, safe extraction, main `.tex` detection, fixed-argument `latexmk` compilation.
- SQLite task, block, glossary, and log persistence.
- LaTeX block parsing with formula, citation, reference, label, graphics, URL, input/include, and skipped environment protection.
- Two-stage glossary review then block-by-block translation with retry and progress tracking.
- Chinese project generation with `ctex` insertion and translated PDF compilation.
- PDF.js side-by-side original/translated preview with synchronized scrolling and shared zoom.
