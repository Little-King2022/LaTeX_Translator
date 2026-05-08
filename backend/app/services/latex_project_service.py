import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Task
from app.services.latex_parser_service import detect_main_tex
from app.services.log_service import add_log


def task_dir(task_id: str) -> Path:
    base = settings.workspace_dir.resolve()
    path = (base / task_id).resolve()
    if not str(path).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid task path")
    return path


def create_task(db: Session, name: str, llm_config_id: int | None = None) -> Task:
    task_id = str(uuid.uuid4())
    root = task_dir(task_id)
    for child in ["upload", "source", "translated", "build_original", "build_translated", "output", "logs"]:
        (root / child).mkdir(parents=True, exist_ok=True)
    task = Task(
        id=task_id,
        name=name,
        status="created",
        source_dir=str(root / "source"),
        translated_dir=str(root / "translated"),
        llm_config_id=llm_config_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    add_log(db, task.id, "info", "task", "Task created")
    return task


async def save_upload(db: Session, task: Task, upload: UploadFile) -> list[str]:
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip LaTeX projects are supported")
    root = task_dir(task.id)
    upload_path = root / "upload" / "original.zip"
    with upload_path.open("wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    source_dir = root / "source"
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True)
    _safe_extract(upload_path, source_dir)
    _flatten_single_root(source_dir)
    candidates = detect_main_tex(source_dir)
    task.status = "uploaded"
    task.main_tex_path = candidates[0] if candidates else None
    task.source_dir = str(source_dir)
    db.commit()
    add_log(db, task.id, "info", "upload", f"Uploaded project. Main candidates: {', '.join(candidates) or 'none'}")
    return candidates


def delete_task_files(task_id: str) -> None:
    path = task_dir(task_id)
    if path.exists():
        shutil.rmtree(path)


def copy_source_to_translated(task: Task) -> Path:
    root = task_dir(task.id)
    source = root / "source"
    translated = root / "translated"
    if translated.exists():
        shutil.rmtree(translated)
    shutil.copytree(source, translated)
    return translated


def package_translated_project(task: Task) -> Path:
    root = task_dir(task.id)
    translated = root / "translated"
    output_zip = root / "output" / "translated_project.zip"
    if output_zip.exists():
        output_zip.unlink()
    shutil.make_archive(str(output_zip.with_suffix("")), "zip", translated)
    return output_zip


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if not str(target).startswith(str(dest_resolved)):
                raise HTTPException(status_code=400, detail="Zip contains unsafe paths")
        zf.extractall(dest)


def _flatten_single_root(source_dir: Path) -> None:
    entries = [entry for entry in source_dir.iterdir() if entry.name != "__MACOSX"]
    if len(entries) != 1 or not entries[0].is_dir():
        return
    inner = entries[0]
    for child in inner.iterdir():
        shutil.move(str(child), source_dir / child.name)
    shutil.rmtree(inner)
