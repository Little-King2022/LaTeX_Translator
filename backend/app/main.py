from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext

from app.api import auth, llm_configs, tasks
from app.core.config import settings
from app.db.database import SessionLocal, init_db
from app.models import LogEntry, Task, TranslationBlock, User
from app.utils.security import get_configured_password_hash


app = FastAPI(title="LaTeX LLM Translator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == settings.app_username).first()
        if not user:
            db.add(User(username=settings.app_username, password_hash=get_configured_password_hash()))
            db.commit()
        _recover_interrupted_tasks(db)
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


def _recover_interrupted_tasks(db) -> None:
    reset_blocks = db.query(TranslationBlock).filter(TranslationBlock.status == "translating").update(
        {TranslationBlock.status: "pending", TranslationBlock.error_message: None}
    )
    tasks = db.query(Task).filter(Task.status == "translating").all()
    for task in tasks:
        task.status = "waiting_glossary_review"
        task.translated_blocks = db.query(TranslationBlock).filter(
            TranslationBlock.task_id == task.id,
            TranslationBlock.status == "completed",
        ).count()
        task.failed_blocks = db.query(TranslationBlock).filter(
            TranslationBlock.task_id == task.id,
            TranslationBlock.status == "failed",
        ).count()
        db.add(
            LogEntry(
                task_id=task.id,
                level="warning",
                module="translation",
                message="Recovered interrupted translation task on backend startup",
            )
        )
    if reset_blocks or tasks:
        db.commit()


app.include_router(auth.router, prefix="/api")
app.include_router(llm_configs.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
