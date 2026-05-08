from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def now_iso() -> str:
    return datetime.utcnow().isoformat()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, default=now_iso, nullable=False)


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="Default")
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    top_p: Mapped[float] = mapped_column(Float, default=1.0)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    timeout: Mapped[int] = mapped_column(Integer, default=120)
    llm_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=now_iso, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, default=now_iso, onupdate=now_iso, nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="created")
    main_tex_path: Mapped[str | None] = mapped_column(String)
    source_dir: Mapped[str] = mapped_column(String, nullable=False)
    translated_dir: Mapped[str | None] = mapped_column(String)
    original_pdf_path: Mapped[str | None] = mapped_column(String)
    translated_pdf_path: Mapped[str | None] = mapped_column(String)
    total_blocks: Mapped[int] = mapped_column(Integer, default=0)
    translated_blocks: Mapped[int] = mapped_column(Integer, default=0)
    failed_blocks: Mapped[int] = mapped_column(Integer, default=0)
    llm_config_id: Mapped[int | None] = mapped_column(ForeignKey("llm_configs.id"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=now_iso, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, default=now_iso, onupdate=now_iso, nullable=False)

    llm_config: Mapped[LLMConfig | None] = relationship()
    blocks: Mapped[list["TranslationBlock"]] = relationship(cascade="all, delete-orphan")
    glossary_terms: Mapped[list["GlossaryTerm"]] = relationship(cascade="all, delete-orphan")
    logs: Mapped[list["LogEntry"]] = relationship(cascade="all, delete-orphan")


class TranslationBlock(Base):
    __tablename__ = "translation_blocks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    protected_text: Mapped[str | None] = mapped_column(Text)
    translated_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=now_iso, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, default=now_iso, onupdate=now_iso, nullable=False)


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    source_term: Mapped[str] = mapped_column(String, nullable=False)
    target_term: Mapped[str] = mapped_column(String, nullable=False)
    term_type: Mapped[str] = mapped_column(String, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    context: Mapped[str | None] = mapped_column(Text)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=now_iso, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, default=now_iso, onupdate=now_iso, nullable=False)


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    module: Mapped[str] = mapped_column(String, nullable=False, default="system")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, default=now_iso, nullable=False)
