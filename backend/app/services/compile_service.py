import asyncio
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Task
from app.services.latex_project_service import task_dir
from app.services.log_service import add_log


LATEXMK_CMD = ["latexmk", "-xelatex", "-interaction=nonstopmode", "-file-line-error", "-halt-on-error"]


async def compile_pdf(db: Session, task: Task, translated: bool = False) -> bool:
    root = task_dir(task.id)
    work_dir = root / ("translated" if translated else "source")
    build_dir = root / ("build_translated" if translated else "build_original")
    output_pdf = root / "output" / ("translated.pdf" if translated else "original.pdf")
    log_name = "compile_translated.log" if translated else "compile_original.log"
    main_rel = Path(task.main_tex_path).with_name("main_zh.tex").as_posix() if translated and task.main_tex_path else task.main_tex_path
    module = "compile_translated" if translated else "compile_original"
    if not main_rel:
        task.error_message = "Main TeX file is not selected"
        db.commit()
        return False
    main_path = (work_dir / main_rel).resolve()
    if not str(main_path).startswith(str(work_dir.resolve())) or not main_path.exists():
        task.error_message = f"Main TeX file not found: {main_rel}"
        db.commit()
        return False
    build_dir.mkdir(parents=True, exist_ok=True)
    cmd = [*LATEXMK_CMD, f"-outdir={build_dir}", str(main_path)]
    add_log(db, task.id, "info", module, f"Running fixed latexmk command for {main_rel}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(work_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.compile_timeout_seconds)
    except TimeoutError:
        task.error_message = "LaTeX compilation timed out"
        db.commit()
        add_log(db, task.id, "error", module, task.error_message)
        return False
    text_log = stdout.decode(errors="ignore") + "\n" + stderr.decode(errors="ignore")
    (root / "logs" / log_name).write_text(text_log, encoding="utf-8")
    add_log(db, task.id, "info" if proc.returncode == 0 else "error", module, text_log[-4000:])
    pdf_name = main_path.with_suffix(".pdf").name
    built_pdf = build_dir / pdf_name
    if proc.returncode != 0 or not built_pdf.exists():
        task.error_message = "LaTeX compilation failed. See logs."
        db.commit()
        return False
    shutil.copy2(built_pdf, output_pdf)
    if translated:
        task.translated_pdf_path = str(output_pdf)
    else:
        task.original_pdf_path = str(output_pdf)
    task.error_message = None
    db.commit()
    return True
