import asyncio
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Task
from app.services.latex_project_service import task_dir
from app.services.log_service import add_log


COMPARISON_LATEXMK_CMD = ["latexmk", "-xelatex", "-interaction=nonstopmode", "-file-line-error", "-halt-on-error"]


async def generate_comparison_pdf(db: Session, task: Task) -> bool:
    root = task_dir(task.id)
    original_pdf = Path(task.original_pdf_path or "")
    translated_pdf = Path(task.translated_pdf_path or "")
    output_pdf = root / "output" / "comparison.pdf"
    build_dir = root / "build_comparison"
    log_path = root / "logs" / "compile_comparison.log"

    if not original_pdf.exists():
        task.error_message = "Original PDF is not available"
        db.commit()
        return False
    if not translated_pdf.exists():
        task.error_message = "Translated PDF is not available"
        db.commit()
        return False

    build_dir.mkdir(parents=True, exist_ok=True)
    tex_path = build_dir / "comparison.tex"
    tex_path.write_text(_comparison_tex(original_pdf, translated_pdf), encoding="utf-8")

    cmd = [*COMPARISON_LATEXMK_CMD, f"-outdir={build_dir}", str(tex_path)]
    add_log(db, task.id, "info", "comparison_pdf", "Generating side-by-side comparison PDF")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(build_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.compile_timeout_seconds)
    except TimeoutError:
        task.error_message = "Comparison PDF generation timed out"
        db.commit()
        add_log(db, task.id, "error", "comparison_pdf", task.error_message)
        return False

    text_log = stdout.decode(errors="ignore") + "\n" + stderr.decode(errors="ignore")
    log_path.write_text(text_log, encoding="utf-8")
    add_log(db, task.id, "info" if proc.returncode == 0 else "error", "comparison_pdf", text_log[-4000:])

    built_pdf = build_dir / "comparison.pdf"
    if proc.returncode != 0 or not built_pdf.exists():
        task.error_message = "Comparison PDF generation failed. See logs."
        db.commit()
        return False

    shutil.copy2(built_pdf, output_pdf)
    task.error_message = None
    db.commit()
    return True


def comparison_pdf_path(task_id: str) -> Path:
    return task_dir(task_id) / "output" / "comparison.pdf"


def _comparison_tex(original_pdf: Path, translated_pdf: Path) -> str:
    original = original_pdf.as_posix()
    translated = translated_pdf.as_posix()
    return rf"""\documentclass{{article}}
\usepackage[a3paper,landscape,margin=8mm]{{geometry}}
\usepackage{{graphicx}}
\pagestyle{{empty}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\fboxsep}}{{0pt}}
\newcount\originalpages
\newcount\translatedpages
\newcount\maxpages
\newcount\currentpage
\originalpages=\XeTeXpdfpagecount "{original}"
\translatedpages=\XeTeXpdfpagecount "{translated}"
\maxpages=\originalpages
\ifnum\translatedpages>\maxpages
  \maxpages=\translatedpages
\fi
\begin{{document}}
\currentpage=1
\loop\ifnum\currentpage<\numexpr\maxpages+1\relax
\noindent
\begin{{minipage}}[c][\textheight][c]{{0.495\textwidth}}
\centering
\ifnum\currentpage<\numexpr\originalpages+1\relax
  \includegraphics[page=\the\currentpage,width=\linewidth,height=\textheight,keepaspectratio]{{{original}}}
\fi
\end{{minipage}}\hfill
\begin{{minipage}}[c][\textheight][c]{{0.495\textwidth}}
\centering
\ifnum\currentpage<\numexpr\translatedpages+1\relax
  \includegraphics[page=\the\currentpage,width=\linewidth,height=\textheight,keepaspectratio]{{{translated}}}
\fi
\end{{minipage}}
\clearpage
\advance\currentpage by 1
\repeat
\end{{document}}
"""
