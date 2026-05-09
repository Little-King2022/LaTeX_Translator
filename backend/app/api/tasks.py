import json
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_current_user
from app.models import GlossaryTerm, LogEntry, Task, TranslationBlock
from app.schemas import (
    GlossaryTermCreate,
    GlossaryTermOut,
    GlossaryTermUpdate,
    LogOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TranslationBlockOut,
    TranslationBlockUpdate,
)
from app.services.latex_parser_service import detect_main_tex
from app.services.latex_project_service import create_task, delete_task_files, save_upload, task_dir
from app.services.log_service import add_log
from app.services.comparison_pdf_service import comparison_pdf_path
from app.workers.runner import run_background
from app.workers.tasks import (
    compile_original_task,
    compile_translated_task,
    extract_glossary_task,
    generate_comparison_pdf_task,
    parse_blocks,
    retranslate_block_task,
    translate_task,
)


router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(db_session)) -> list[Task]:
    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    for task in tasks:
        _attach_task_metrics(task)
    return tasks


@router.post("", response_model=TaskOut)
def create(payload: TaskCreate, db: Session = Depends(db_session)) -> Task:
    task = create_task(db, payload.name, payload.llm_config_id)
    _attach_task_metrics(task)
    return task


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(db_session)) -> Task:
    return _get_task(db, task_id)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdate, db: Session = Depends(db_session)) -> Task:
    task = _get_task(db, task_id)
    task.name = payload.name.strip()
    db.commit()
    db.refresh(task)
    _attach_task_metrics(task)
    return task


@router.delete("/{task_id}")
def delete_task(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    task = _get_task(db, task_id)
    db.delete(task)
    db.commit()
    delete_task_files(task_id)
    return {"ok": True}


@router.post("/{task_id}/upload")
async def upload_task(task_id: str, file: UploadFile = File(...), db: Session = Depends(db_session)) -> dict:
    task = _get_task(db, task_id)
    candidates = await save_upload(db, task, file)
    if task.main_tex_path:
        run_background(compile_original_task, task.id)
    return {"ok": True, "main_candidates": candidates, "selected": task.main_tex_path}


@router.post("/{task_id}/detect-main")
def detect_main(task_id: str, main_tex_path: str | None = None, db: Session = Depends(db_session)) -> dict:
    task = _get_task(db, task_id)
    candidates = detect_main_tex(Path(task.source_dir))
    if main_tex_path:
        if main_tex_path not in candidates and not (Path(task.source_dir) / main_tex_path).exists():
            raise HTTPException(status_code=400, detail="Selected main TeX file does not exist")
        task.main_tex_path = main_tex_path
        db.commit()
    return {"main_candidates": candidates, "selected": task.main_tex_path}


@router.post("/{task_id}/compile-original")
async def compile_original(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    _get_task(db, task_id)
    return {"queued": run_background(compile_original_task, task_id)}


@router.post("/{task_id}/extract-glossary")
async def extract_glossary(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    _get_task(db, task_id)
    return {"queued": run_background(extract_glossary_task, task_id)}


@router.post("/{task_id}/start-translation")
async def start_translation(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    _get_task(db, task_id)
    return {"queued": run_background(translate_task, task_id)}


@router.post("/{task_id}/compile-translated")
async def compile_translated(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    _get_task(db, task_id)
    return {"queued": run_background(compile_translated_task, task_id)}


@router.post("/{task_id}/generate-comparison-pdf")
async def generate_comparison_pdf(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    _get_task(db, task_id)
    return {"queued": run_background(generate_comparison_pdf_task, task_id)}


@router.post("/{task_id}/retry-failed-blocks")
async def retry_failed(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    task = _get_task(db, task_id)
    db.query(TranslationBlock).filter(TranslationBlock.task_id == task.id, TranslationBlock.status == "failed").update(
        {TranslationBlock.status: "pending", TranslationBlock.error_message: None}
    )
    db.commit()
    return {"queued": run_background(translate_task, task_id)}


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    task = _get_task(db, task_id)
    task.status = "cancelled"
    db.commit()
    add_log(db, task.id, "warning", "task", "Task cancellation requested")
    return {"ok": True}


@router.get("/{task_id}/glossary", response_model=list[GlossaryTermOut])
def list_glossary(task_id: str, db: Session = Depends(db_session)) -> list[GlossaryTerm]:
    _get_task(db, task_id)
    return db.query(GlossaryTerm).filter(GlossaryTerm.task_id == task_id).order_by(GlossaryTerm.source_term).all()


@router.post("/{task_id}/glossary", response_model=GlossaryTermOut)
def add_glossary(task_id: str, payload: GlossaryTermCreate, db: Session = Depends(db_session)) -> GlossaryTerm:
    _get_task(db, task_id)
    term = GlossaryTerm(task_id=task_id, **payload.model_dump())
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


@router.put("/{task_id}/glossary/{term_id}", response_model=GlossaryTermOut)
def update_glossary(task_id: str, term_id: int, payload: GlossaryTermUpdate, db: Session = Depends(db_session)) -> GlossaryTerm:
    _get_task(db, task_id)
    term = db.get(GlossaryTerm, term_id)
    if not term or term.task_id != task_id:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    for key, value in payload.model_dump().items():
        setattr(term, key, value)
    db.commit()
    db.refresh(term)
    return term


@router.delete("/{task_id}/glossary/{term_id}")
def delete_glossary(task_id: str, term_id: int, db: Session = Depends(db_session)) -> dict[str, bool]:
    _get_task(db, task_id)
    term = db.get(GlossaryTerm, term_id)
    if not term or term.task_id != task_id:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    db.delete(term)
    db.commit()
    return {"ok": True}


@router.post("/{task_id}/glossary/import")
async def import_glossary(task_id: str, file: UploadFile = File(...), db: Session = Depends(db_session)) -> dict:
    _get_task(db, task_id)
    raw = (await file.read()).decode("utf-8")
    items = json.loads(raw)
    count = 0
    for item in items:
        db.add(GlossaryTerm(task_id=task_id, **item))
        count += 1
    db.commit()
    return {"imported": count}


@router.get("/{task_id}/glossary/export")
def export_glossary(task_id: str, db: Session = Depends(db_session)) -> PlainTextResponse:
    _get_task(db, task_id)
    terms = db.query(GlossaryTerm).filter(GlossaryTerm.task_id == task_id).all()
    payload = [
        {
            "source_term": term.source_term,
            "target_term": term.target_term,
            "term_type": term.term_type,
            "frequency": term.frequency,
            "context": term.context,
            "is_locked": term.is_locked,
        }
        for term in terms
    ]
    return PlainTextResponse(json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json")


@router.get("/{task_id}/glossary/conflicts")
def glossary_conflicts(task_id: str, db: Session = Depends(db_session)) -> list[dict]:
    _get_task(db, task_id)
    grouped: dict[str, set[str]] = defaultdict(set)
    terms = db.query(GlossaryTerm).filter(GlossaryTerm.task_id == task_id).all()
    for term in terms:
        grouped[term.source_term.strip()].add(term.target_term.strip())
    return [
        {"source_term": source, "target_terms": sorted(targets)}
        for source, targets in sorted(grouped.items())
        if source and len(targets) > 1
    ]


@router.get("/{task_id}/blocks", response_model=list[TranslationBlockOut])
def list_blocks(task_id: str, db: Session = Depends(db_session)) -> list[TranslationBlock]:
    task = _get_task(db, task_id)
    if not task.total_blocks:
        parse_blocks(db, task)
    return db.query(TranslationBlock).filter(TranslationBlock.task_id == task_id).order_by(TranslationBlock.block_index).all()


@router.get("/{task_id}/blocks/{block_id}", response_model=TranslationBlockOut)
def get_block(task_id: str, block_id: str, db: Session = Depends(db_session)) -> TranslationBlock:
    _get_task(db, task_id)
    block = db.get(TranslationBlock, block_id)
    if not block or block.task_id != task_id:
        raise HTTPException(status_code=404, detail="Block not found")
    return block


@router.put("/{task_id}/blocks/{block_id}", response_model=TranslationBlockOut)
def update_block(task_id: str, block_id: str, payload: TranslationBlockUpdate, db: Session = Depends(db_session)) -> TranslationBlock:
    task = _get_task(db, task_id)
    block = db.get(TranslationBlock, block_id)
    if not block or block.task_id != task_id:
        raise HTTPException(status_code=404, detail="Block not found")
    block.translated_text = payload.translated_text
    block.status = payload.status
    task.translated_blocks = db.query(TranslationBlock).filter(TranslationBlock.task_id == task.id, TranslationBlock.status == "completed").count()
    task.failed_blocks = db.query(TranslationBlock).filter(TranslationBlock.task_id == task.id, TranslationBlock.status == "failed").count()
    db.commit()
    db.refresh(block)
    return block


@router.post("/{task_id}/blocks/{block_id}/retranslate")
async def retranslate_block(task_id: str, block_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    _get_task(db, task_id)
    return {"queued": run_background(retranslate_block_task, task_id, block_id)}


@router.post("/{task_id}/blocks/batch-retranslate")
async def batch_retranslate(
    task_id: str,
    block_ids: list[str] = Body(...),
    db: Session = Depends(db_session),
) -> dict[str, int | bool]:
    _get_task(db, task_id)
    if not block_ids:
        raise HTTPException(status_code=400, detail="No blocks selected")
    count = (
        db.query(TranslationBlock)
        .filter(TranslationBlock.task_id == task_id, TranslationBlock.id.in_(block_ids))
        .update({TranslationBlock.status: "pending", TranslationBlock.error_message: None}, synchronize_session=False)
    )
    db.commit()
    return {"updated": count, "queued": run_background(translate_task, task_id)}


@router.get("/{task_id}/pdf/original")
def original_pdf(task_id: str, db: Session = Depends(db_session)) -> FileResponse:
    task = _get_task(db, task_id)
    return _file(task.original_pdf_path, "original.pdf")


@router.get("/{task_id}/pdf/translated")
def translated_pdf(task_id: str, db: Session = Depends(db_session)) -> FileResponse:
    task = _get_task(db, task_id)
    return _file(task.translated_pdf_path, "translated.pdf")


@router.get("/{task_id}/pdf/comparison")
def comparison_pdf(task_id: str, db: Session = Depends(db_session)) -> FileResponse:
    _get_task(db, task_id)
    return _file(str(comparison_pdf_path(task_id)), "comparison.pdf")


@router.get("/{task_id}/pdf/comparison/status")
def comparison_pdf_status(task_id: str, db: Session = Depends(db_session)) -> dict[str, bool]:
    _get_task(db, task_id)
    return {"exists": comparison_pdf_path(task_id).exists()}


@router.get("/{task_id}/download/original-pdf")
def download_original_pdf(task_id: str, db: Session = Depends(db_session)) -> FileResponse:
    task = _get_task(db, task_id)
    return _file(task.original_pdf_path, "original.pdf", attachment=True)


@router.get("/{task_id}/download/translated-pdf")
def download_translated_pdf(task_id: str, db: Session = Depends(db_session)) -> FileResponse:
    task = _get_task(db, task_id)
    return _file(task.translated_pdf_path, "translated.pdf", attachment=True)


@router.get("/{task_id}/download/comparison-pdf")
def download_comparison_pdf(task_id: str, db: Session = Depends(db_session)) -> FileResponse:
    _get_task(db, task_id)
    return _file(str(comparison_pdf_path(task_id)), "comparison.pdf", attachment=True)


@router.get("/{task_id}/download/translated-project")
def download_translated_project(task_id: str, db: Session = Depends(db_session)) -> FileResponse:
    _get_task(db, task_id)
    path = task_dir(task_id) / "output" / "translated_project.zip"
    return _file(str(path), "translated_project.zip", attachment=True)


@router.get("/{task_id}/logs", response_model=list[LogOut])
def logs(task_id: str, db: Session = Depends(db_session)) -> list[LogEntry]:
    _get_task(db, task_id)
    return db.query(LogEntry).filter(LogEntry.task_id == task_id).order_by(LogEntry.id.desc()).limit(500).all()


def _get_task(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _attach_task_metrics(task)
    return task


def _attach_task_metrics(task: Task) -> None:
    task.pending_blocks = max(task.total_blocks - task.translated_blocks - task.failed_blocks, 0)


def _file(path: str | None, filename: str, attachment: bool = False) -> FileResponse:
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail=f"{filename} is not available")
    disposition = "attachment" if attachment else "inline"
    return FileResponse(path, filename=filename, media_type="application/pdf" if filename.endswith(".pdf") else None, content_disposition_type=disposition)
