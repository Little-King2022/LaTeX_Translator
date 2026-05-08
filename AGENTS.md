# AGENTS.md

This file gives future coding agents the current project context and the rules that matter when modifying this repository.

## Project Summary

LaTeX LLM Translator is a single-user web app that translates English LaTeX paper projects into Chinese at the source level.

Main flow:

```text
upload LaTeX zip
detect main .tex
compile original PDF
parse translatable LaTeX blocks
extract and review glossary
translate blocks with an OpenAI-compatible LLM
generate translated LaTeX project
compile translated PDF
preview/download original, translated, and comparison PDFs
```

## Current Runtime

Repository root:

```text
/data2/jinchuanjing/LaTeX_Translator
```

Docker services:

```text
frontend: http://localhost:3000
backend:  http://localhost:18000
redis:    localhost:6379
```

Useful checks:

```bash
docker compose ps
curl --noproxy '*' http://127.0.0.1:18000/api/health
docker compose logs --tail=120 backend
```

Use `--noproxy '*'` for local `curl` calls when the environment has proxy variables set.

Default login in development:

```text
username: admin
password: admin
```

## Important Directories

```text
backend/app/api/          FastAPI routes
backend/app/core/         settings
backend/app/db/           SQLAlchemy setup
backend/app/models/       database models
backend/app/services/     LaTeX, LLM, glossary, compile, PDF services
backend/app/workers/      background runner and task orchestration
frontend/src/             Vue app
workspace/tasks/          task workspaces, ignored by git
data/                     SQLite database, ignored by git
```

Do not commit `workspace/`, `data/`, build outputs, `.env`, `node_modules`, or Python cache files.

## Key Implementation Notes

- Backend: FastAPI, SQLAlchemy, SQLite, httpx, latexmk/XeLaTeX.
- Frontend: Vue 3, Vite, Element Plus.
- Long-running upload, compile, glossary, translation, and comparison-PDF actions are queued through `backend/app/workers/runner.py`.
- LLM calls go through `backend/app/services/llm_client.py`.
- LaTeX block extraction and placeholder protection live in `backend/app/services/latex_parser_service.py`.
- Translated project generation and task orchestration live in `backend/app/workers/tasks.py`.
- PDF comparison generation lives in `backend/app/services/comparison_pdf_service.py`.

## Translation and LaTeX Rules

- Translate LaTeX source blocks, not rendered PDFs.
- Never send the full paper to the LLM as one request.
- Preserve formulas, citations, labels, refs, URLs, graphics, input/include commands, and placeholders.
- Do not overwrite `source/`; write generated Chinese files under `translated/`.
- Do not translate `.bib` files by default.
- Keep parser behavior conservative. A valid partially translated project is better than broken LaTeX.
- For Chinese output, preserve the original document class and insert Chinese support packages instead of changing the template to `ctexart`.

## PDF Preview Notes

The current frontend uses browser-native PDF rendering in an iframe.

Browser-native PDF viewers do not expose reliable JavaScript scroll APIs, so do not assume synchronized iframe scrolling is available. For stable bilingual viewing, use the backend-generated `output/comparison.pdf`, which places English and Chinese pages side by side.

## Common Commands

Build and run:

```bash
docker compose up --build
```

Restart backend after backend code changes in the running Docker setup:

```bash
docker compose restart backend
```

Backend syntax check:

```bash
python -m compileall backend/app
```

Frontend build:

```bash
cd frontend
npm run build
```

Inspect a task from inside the backend container:

```bash
docker compose exec backend python -c "from app.db.database import SessionLocal; from app.models import Task; db=SessionLocal(); print(db.query(Task).all()); db.close()"
```

## Current Git Baseline

The repository was initialized during development. The initial baseline commit is:

```text
9cd6acf Initial LaTeX translator baseline
```

When making risky changes, keep them separate from this baseline and avoid mixing unrelated cleanup with behavior changes.

## Development Guidelines

- Prefer existing local patterns over new abstractions.
- Keep backend changes scoped to the service or route involved.
- Add validation around parser and compiler changes; real LaTeX task validation is valuable.
- For frontend changes, keep the interface utilitarian and consistent with Element Plus.
- Do not revert user changes unless explicitly requested.
- If Docker is running from an already-built image, source edits may need a rebuild or a targeted container sync plus restart for immediate validation.

## Known Constraints

- Single-user authentication only.
- Translation quality and latency depend heavily on the configured LLM.
- Complex custom macros and table bodies may need parser enhancements.
- LaTeX compilation is run with fixed arguments inside the backend container and is intended for trusted or controlled deployments.
- The backend port is `18000:8000` in `docker-compose.yml`.
