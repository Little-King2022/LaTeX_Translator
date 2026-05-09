import asyncio
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import GlossaryTerm, LLMConfig, Task, TranslationBlock
from app.services.comparison_pdf_service import generate_comparison_pdf
from app.services.compile_service import compile_pdf
from app.services.glossary_service import (
    FALLBACK_CONTEXT,
    extract_glossary_with_llm,
    fallback_candidate_terms,
    glossary_text,
    reset_glossary_progress,
    write_glossary_progress,
)
from app.services.latex_parser_service import (
    apply_translations,
    clean_llm_output,
    ensure_ctex,
    extract_blocks,
    normalize_placeholders,
    restore_placeholders,
    validate_translation,
)
from app.services.latex_project_service import copy_source_to_translated, package_translated_project
from app.services.llm_client import LLMClient
from app.services.log_service import add_log


def parse_blocks(db: Session, task: Task) -> None:
    blocks = extract_blocks(Path(task.source_dir))
    existing_blocks = db.query(TranslationBlock).filter(TranslationBlock.task_id == task.id).all()
    existing_keys = {_block_key(block.file_path, block.block_type, block.source_text) for block in existing_blocks}
    added = 0
    for block in blocks:
        key = _block_key(block.file_path, block.block_type, block.source_text)
        if key in existing_keys:
            continue
        db.add(
            TranslationBlock(
                id=f"{task.id}-{block.id}",
                task_id=task.id,
                file_path=block.file_path,
                block_index=block.block_index,
                block_type=block.block_type,
                source_text=block.source_text,
                protected_text=block.protected_text,
                status="pending",
            )
        )
        existing_keys.add(key)
        added += 1
    task.total_blocks = len(existing_blocks) + added
    db.commit()
    if added:
        add_log(db, task.id, "info", "parser", f"Added {added} newly detected translatable blocks")
    elif not existing_blocks:
        add_log(db, task.id, "info", "parser", "No translatable blocks detected")


def _block_key(file_path: str, block_type: str, source_text: str | None) -> tuple[str, str, str]:
    normalized = " ".join((source_text or "").split())
    return file_path, block_type, normalized


async def compile_original_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            return
        task.status = "compiling_original"
        db.commit()
        ok = await compile_pdf(db, task, translated=False)
        task.status = "uploaded" if ok else "failed"
        db.commit()
    finally:
        db.close()


async def extract_glossary_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            return
        task.status = "extracting"
        task.error_message = None
        db.commit()
        reset_glossary_progress(task.id)
        write_glossary_progress(task.id, "parsing_blocks", "正在解析 LaTeX 翻译块", 10)
        parse_blocks(db, task)
        removed = (
            db.query(GlossaryTerm)
            .filter(GlossaryTerm.task_id == task.id, GlossaryTerm.context == FALLBACK_CONTEXT)
            .delete()
        )
        if removed:
            db.commit()
            add_log(db, task.id, "info", "glossary", f"Removed {removed} fallback glossary terms before retry")
        config = _get_llm_config(db, task)
        client = LLMClient(config.base_url, config.api_key, config.model, config.timeout)
        try:
            terms = await extract_glossary_with_llm(db, task.id, client, config)
            add_log(db, task.id, "info", "glossary", f"Extracted {len(terms)} glossary terms")
        except Exception as exc:
            write_glossary_progress(task.id, "fallback", f"LLM 术语提取失败，正在生成本地候选：{exc}", 80)
            add_log(db, task.id, "error", "glossary", f"LLM glossary extraction failed: {exc}")
            terms = fallback_candidate_terms(db, task.id)
            write_glossary_progress(task.id, "completed", f"已生成 {len(terms)} 个本地候选术语", 100, terms_count=len(terms))
            add_log(db, task.id, "warning", "glossary", f"Generated {len(terms)} fallback candidate terms")
        task.status = "waiting_glossary_review"
        db.commit()
    finally:
        db.close()


async def translate_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            return
        task.status = "translating"
        task.error_message = None
        db.commit()
        parse_blocks(db, task)
        config = _get_llm_config(db, task)
        config_data = _llm_config_snapshot(config)
        glossary = glossary_text(db, task.id)
        pending_blocks = (
            db.query(TranslationBlock)
            .filter(TranslationBlock.task_id == task.id, TranslationBlock.status.in_(["pending", "failed"]))
            .order_by(TranslationBlock.block_index)
            .all()
        )
        block_ids = [block.id for block in pending_blocks]
        concurrency = _translation_concurrency(config_data)
        add_log(db, task.id, "info", "translation", f"Starting LLM translation with concurrency={concurrency}")
    finally:
        db.close()

    semaphore = asyncio.Semaphore(concurrency)
    jobs = [
        asyncio.create_task(_translate_block_in_session(task_id, block_id, config_data, glossary, semaphore))
        for block_id in block_ids
    ]
    for job in asyncio.as_completed(jobs):
        try:
            await job
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            db = SessionLocal()
            try:
                add_log(db, task_id, "error", "translation", f"Unexpected translation worker failure: {exc}")
            finally:
                db.close()

        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            if not task:
                return
            _refresh_task_counts(db, task)
            cancelled = task.status == "cancelled"
            db.commit()
        finally:
            db.close()
        if cancelled:
            for queued_job in jobs:
                if not queued_job.done():
                    queued_job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            return

    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            return
        _refresh_task_counts(db, task)
        if task.failed_blocks:
            task.status = "failed"
            task.error_message = f"{task.failed_blocks} blocks failed translation"
            db.commit()
            return
        _generate_translated_project(db, task)
        task.status = "compiling_translated"
        db.commit()
        ok = await compile_pdf(db, task, translated=True)
        package_translated_project(task)
        task.status = "completed" if ok else "failed"
        db.commit()
    finally:
        db.close()


async def compile_translated_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            return
        task.status = "compiling_translated"
        db.commit()
        completed = db.query(TranslationBlock).filter(TranslationBlock.task_id == task.id, TranslationBlock.status == "completed").count()
        if completed:
            _generate_translated_project(db, task)
        ok = await compile_pdf(db, task, translated=True)
        if ok:
            package_translated_project(task)
        task.status = "completed" if ok else "failed"
        db.commit()
    finally:
        db.close()


async def generate_comparison_pdf_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if not task:
            return
        await generate_comparison_pdf(db, task)
    finally:
        db.close()


async def retranslate_block_task(task_id: str, block_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        block = db.get(TranslationBlock, block_id)
        if not task or not block:
            return
        config = _get_llm_config(db, task)
        client = LLMClient(config.base_url, config.api_key, config.model, config.timeout)
        await _translate_block(db, block, client, config, glossary_text(db, task.id), None)
        _refresh_task_counts(db, task)
        db.commit()
    finally:
        db.close()


async def _translate_block_in_session(
    task_id: str,
    block_id: str,
    config,
    glossary: str,
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            block = db.get(TranslationBlock, block_id)
            if not task or not block or task.status == "cancelled":
                return
            client = LLMClient(config.base_url, config.api_key, config.model, config.timeout)
            await _translate_block(db, block, client, config, glossary, None)
        finally:
            db.close()


async def _translate_block(
    db: Session,
    block: TranslationBlock,
    client: LLMClient,
    config,
    glossary: str,
    semaphore: asyncio.Semaphore | None,
) -> None:
    prompt = f"""你是农业工程、计算机视觉、深度学习和作物表型分析领域的英文学术论文翻译助手。

请将以下英文 LaTeX 论文内容翻译为中文。

【最高优先级规则】
- 你的输出必须从翻译后的 LaTeX 内容的第一个字符开始，到最后一个字符结束。
- 禁止输出任何思考过程、翻译策略讨论、术语选择说明、自我指令、备忘或任何形式的元文本。
- 禁止输出形如 "译为..."、"应译为..."、"可以译为..."、"保存..."、"注意..." 等翻译笔记。
- 如果术语库中有对应术语，直接使用，不要说明你的选择。

【翻译规则】
1. 保留所有 LaTeX 命令、环境、数学公式、引用命令、标签和占位符不变；
2. 不修改任何形如 @@LATEX_PLACEHOLDER_0001@@ 的占位符；
3. 不修改 \\cite{{}}、\\ref{{}}、\\label{{}}、\\autoref{{}}、\\cref{{}}、\\Cref{{}}、\\url{{}}、\\href{{}} 等命令；
4. 不翻译变量名、模型名、数据集名、文件路径和代码片段；
5. 中文表达应符合正式学术论文风格；
6. 严格使用给定术语库；
7. 不输出 Markdown 代码块；
8. 只输出翻译后的 LaTeX 内容，不输出任何其他内容。

术语库：
{glossary}
"""
    last_error = None
    for attempt in range(3):
        try:
            if _task_cancelled(db, block.task_id):
                return
            if semaphore:
                async with semaphore:
                    output = await _run_llm_translation_attempt(db, block, client, config, prompt)
            else:
                output = await _run_llm_translation_attempt(db, block, client, config, prompt)
            if output is None:
                return
            cleaned = clean_llm_output(output)
            cleaned = normalize_placeholders(cleaned, block.source_text)
            error = validate_translation(block.protected_text or block.source_text, cleaned)
            if error:
                raise ValueError(error)
            block.translated_text = restore_placeholders(cleaned, block.source_text)
            block.status = "completed"
            block.error_message = None
            db.commit()
            return
        except Exception as exc:
            last_error = str(exc)
            add_log(db, block.task_id, "warning", "translation", f"Block {block.id} attempt {attempt + 1} failed: {exc}")
    block.status = "failed"
    block.error_message = last_error
    db.commit()


async def _run_llm_translation_attempt(db: Session, block: TranslationBlock, client: LLMClient, config, prompt: str) -> str | None:
    db.refresh(block)
    if _task_cancelled(db, block.task_id):
        return None
    block.status = "translating"
    block.error_message = None
    db.commit()
    return await asyncio.wait_for(
        client.chat(
            [{"role": "system", "content": prompt}, {"role": "user", "content": block.protected_text or block.source_text}],
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            top_p=config.top_p,
            stream=False,
        ),
        timeout=config.timeout,
    )


def _generate_translated_project(db: Session, task: Task) -> None:
    translated = copy_source_to_translated(task)
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    blocks = db.query(TranslationBlock).filter(TranslationBlock.task_id == task.id, TranslationBlock.status == "completed").all()
    for block in blocks:
        grouped[block.file_path].append((block.source_text, block.translated_text or block.source_text, block.block_type))
    apply_translations(Path(task.source_dir), translated, grouped)
    if task.main_tex_path:
        main_path = translated / task.main_tex_path
        zh_main = main_path.with_name("main_zh.tex")
        ensure_ctex(main_path, zh_main)
    add_log(db, task.id, "info", "translation", "Generated translated LaTeX project")


def _refresh_task_counts(db: Session, task: Task) -> None:
    task.translated_blocks = db.query(TranslationBlock).filter(
        TranslationBlock.task_id == task.id,
        TranslationBlock.status == "completed",
    ).count()
    task.failed_blocks = db.query(TranslationBlock).filter(
        TranslationBlock.task_id == task.id,
        TranslationBlock.status == "failed",
    ).count()


def _task_cancelled(db: Session, task_id: str) -> bool:
    status = db.query(Task.status).filter(Task.id == task_id).scalar()
    return status == "cancelled"


def _llm_config_snapshot(config: LLMConfig) -> SimpleNamespace:
    return SimpleNamespace(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        temperature=config.temperature,
        top_p=config.top_p,
        max_tokens=config.max_tokens,
        timeout=config.timeout,
        llm_concurrency=config.llm_concurrency,
    )


def _translation_concurrency(config) -> int:
    try:
        value = int(getattr(config, "llm_concurrency", 1) or 1)
    except (TypeError, ValueError):
        value = 1
    return max(1, min(value, 16))


def _get_llm_config(db: Session, task: Task) -> LLMConfig:
    config = db.get(LLMConfig, task.llm_config_id) if task.llm_config_id else None
    if not config:
        config = db.query(LLMConfig).filter(LLMConfig.is_default.is_(True)).first()
    if not config:
        config = db.query(LLMConfig).first()
    if not config:
        raise RuntimeError("No LLM configuration available")
    return config
