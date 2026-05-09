import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from app.models import GlossaryTerm, TranslationBlock
from app.services.latex_parser_service import clean_llm_output
from app.services.llm_client import LLMClient


TERM_TYPES = {
    "technical_term",
    "model_name",
    "dataset_name",
    "metric",
    "abbreviation",
    "person_name",
    "do_not_translate",
}
GLOSSARY_TEXT_LIMIT = 12000
GLOSSARY_PREVIEW_LIMIT = 4000
FALLBACK_CONTEXT = "Fallback candidate. Please revise before translation."
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "these",
    "this",
    "to",
    "using",
    "was",
    "we",
    "were",
    "with",
}


async def extract_glossary_with_llm(db: Session, task_id: str, client: LLMClient, config) -> list[GlossaryTerm]:
    blocks = db.query(TranslationBlock).filter(TranslationBlock.task_id == task_id).order_by(TranslationBlock.block_index).all()
    write_glossary_progress(task_id, "preparing", "正在整理可提取术语的论文片段", 20)
    text = _build_glossary_source_text(blocks)
    write_glossary_progress(task_id, "requesting_llm", "正在请求 LLM 提取术语和人名", 30)
    prompt = """你是农业工程、计算机视觉、深度学习和作物表型分析领域的学术论文术语提取助手。

请从以下英文 LaTeX 论文文本中提取重要术语和文中出现的重要人名，并给出推荐中文译名或保留形式。
你必须输出严格合法的 JSON object。

要求：
1. 提取专业术语、算法名、模型名、数据集名、评价指标、缩写、人名和不应翻译的专有名词；
2. 不要提取普通英语单词；
3. 不要修改 LaTeX 命令、公式、引用和标签；
4. 输出 JSON object，顶层只包含 terms 字段；
5. terms 是 JSON array，每个元素包含 source_term、target_term、term_type、context；
6. 对模型名、数据集名、缩写，如果建议保留英文，则 target_term 与 source_term 相同；
7. 对人名使用 term_type="person_name"，优先提取完整姓名，例如 "Li Yan"、"Zhang Lei"、"Geoffrey Hinton"，不要只提取单个姓氏或名字；
8. 人名出现在作者、致谢、贡献声明、数据采集人员、方法命名来源或正文叙述中时都应提取；不要把引用命令、文献 key、机构名或项目名当做人名；
9. 人名的 target_term 若无法确定规范中文写法，应与 source_term 保持一致，避免臆造译名；
10. 不输出 Markdown，不输出解释。
11. 必须输出严格合法 JSON，所有键名和字符串必须使用双引号，不能有尾随逗号。
12. 最多输出 40 个最重要条目，其中人名不应被专业术语挤掉。

term_type 只能从以下值中选择：
technical_term, model_name, dataset_name, metric, abbreviation, person_name, do_not_translate

示例 JSON 输出：
{
  "terms": [
    {
      "source_term": "UAV imagery",
      "target_term": "无人机影像",
      "term_type": "technical_term",
      "context": "UAV imagery was used for plot-level phenotyping."
    },
    {
      "source_term": "Li Yan",
      "target_term": "Li Yan",
      "term_type": "person_name",
      "context": "Acknowledgments: Li Yan contributed to UAV image acquisition."
    }
  ]
}
"""
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": text}]
    json_response_format = {"type": "json_object"}
    content = ""
    last_progress_at = 0.0

    async def on_delta(_delta: str, accumulated: str) -> None:
        nonlocal last_progress_at
        now = time.monotonic()
        if now - last_progress_at < 0.6 and len(accumulated) < GLOSSARY_PREVIEW_LIMIT:
            return
        last_progress_at = now
        percent = min(70, 35 + len(accumulated) // 600)
        write_glossary_progress(
            task_id,
            "streaming",
            "LLM 正在返回术语候选",
            percent,
            preview=_preview_text(accumulated),
        )

    try:
        content = await client.chat_stream(
            messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            top_p=config.top_p,
            on_delta=on_delta,
            response_format=json_response_format,
        )
    except Exception as exc:
        write_glossary_progress(
            task_id,
            "requesting_llm",
            f"流式响应不可用，正在切换为普通请求：{exc}",
            35,
        )
    if not content:
        try:
            content = await client.chat(
                messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                stream=False,
                response_format=json_response_format,
            )
        except Exception as exc:
            write_glossary_progress(
                task_id,
                "requesting_llm",
                f"JSON Output 请求不可用，正在切换为普通请求：{exc}",
                35,
            )
            content = await client.chat(
                messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                stream=False,
            )
    write_glossary_progress(
        task_id,
        "parsing_json",
        "LLM 响应已收到，正在解析 JSON",
        75,
        preview=_preview_text(content),
    )
    _write_glossary_raw_log(task_id, content)
    parsed = parse_glossary_json(content)
    write_glossary_progress(task_id, "saving_terms", f"正在保存 {len(parsed)} 个术语候选", 85, preview=_preview_text(content))
    existing = {term.source_term.lower() for term in db.query(GlossaryTerm).filter(GlossaryTerm.task_id == task_id).all()}
    terms: list[GlossaryTerm] = []
    for item in parsed:
        source = str(item.get("source_term", "")).strip()
        target = str(item.get("target_term", source)).strip()
        term_type = str(item.get("term_type", "technical_term")).strip()
        if not source or source.lower() in existing:
            continue
        if term_type not in TERM_TYPES:
            term_type = "technical_term"
        term = GlossaryTerm(
            task_id=task_id,
            source_term=source,
            target_term=target or source,
            term_type=term_type,
            frequency=1,
            context=str(item.get("context", ""))[:1000],
            is_locked=term_type in {"model_name", "dataset_name", "abbreviation", "person_name", "do_not_translate"},
        )
        db.add(term)
        terms.append(term)
        existing.add(source.lower())
    db.commit()
    write_glossary_progress(
        task_id,
        "completed",
        f"术语提取完成，新增 {len(terms)} 条",
        100,
        preview=_preview_text(content),
        terms_count=len(terms),
    )
    return terms


def reset_glossary_progress(task_id: str) -> None:
    write_glossary_progress(task_id, "queued", "术语提取已加入后台队列", 1, preview="", terms_count=0)


def write_glossary_progress(
    task_id: str,
    status: str,
    message: str,
    percent: int,
    preview: str | None = None,
    terms_count: int | None = None,
) -> None:
    payload = read_glossary_progress(task_id)
    payload.update(
        {
            "status": status,
            "message": message,
            "percent": max(0, min(100, percent)),
            "updated_at": datetime.utcnow().isoformat(),
        }
    )
    if preview is not None:
        payload["preview"] = preview
    if terms_count is not None:
        payload["terms_count"] = terms_count
    path = _glossary_progress_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def read_glossary_progress(task_id: str) -> dict:
    path = _glossary_progress_path(task_id)
    if not path.exists():
        return {
            "status": "idle",
            "message": "",
            "percent": 0,
            "preview": "",
            "terms_count": 0,
            "updated_at": None,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "idle",
            "message": "",
            "percent": 0,
            "preview": "",
            "terms_count": 0,
            "updated_at": None,
        }
    return data if isinstance(data, dict) else {}


def _glossary_progress_path(task_id: str) -> Path:
    root = Path("workspace/tasks") / task_id
    if not root.exists():
        root = Path("/app/workspace/tasks") / task_id
    return root / "logs" / "glossary_progress.json"


def _preview_text(text: str) -> str:
    return text[-GLOSSARY_PREVIEW_LIMIT:]


def parse_glossary_json(content: str) -> list[dict]:
    cleaned = clean_llm_output(content)
    if not cleaned:
        raise ValueError("LLM returned empty glossary content")
    candidates = [cleaned]
    array_text = _extract_json_array(cleaned)
    if array_text and array_text != cleaned:
        candidates.append(array_text)
    for candidate in list(candidates):
        repaired = _repair_common_json_issues(candidate)
        if repaired != candidate:
            candidates.append(repaired)
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
            if isinstance(parsed, dict) and isinstance(parsed.get("terms"), list):
                return [item for item in parsed["terms"] if isinstance(item, dict)]
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error:
        start = max(last_error.pos - 240, 0)
        end = min(last_error.pos + 240, len(candidates[-1]))
        nearby = candidates[-1][start:end]
        raise ValueError(f"Invalid glossary JSON at line {last_error.lineno}, column {last_error.colno}: {nearby}")
    raise ValueError("LLM did not return a JSON array")


def _extract_json_array(text: str) -> str | None:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1].strip()


def _repair_common_json_issues(text: str) -> str:
    repaired = text.strip()
    repaired = re.sub(r"//.*?$", "", repaired, flags=re.M)
    repaired = re.sub(r"/\*.*?\*/", "", repaired, flags=re.S)
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = re.sub(r"([{,]\s*)(source_term|target_term|term_type|context|frequency|is_locked)\s*:", r'\1"\2":', repaired)
    return repaired


def _write_glossary_raw_log(task_id: str, content: str) -> None:
    root = Path("workspace/tasks") / task_id
    if not root.exists():
        root = Path("/app/workspace/tasks") / task_id
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "extract_terms.log").write_text(content or "", encoding="utf-8")


def _build_glossary_source_text(blocks: list[TranslationBlock]) -> str:
    priority_types = {"title", "abstract", "section", "subsection", "subsubsection", "caption"}
    selected: list[str] = []
    total = 0

    def add_block(block: TranslationBlock) -> None:
        nonlocal total
        text = (block.protected_text or block.source_text).strip()
        if not text:
            return
        remaining = GLOSSARY_TEXT_LIMIT - total
        if remaining <= 0:
            return
        selected.append(text[:remaining])
        total += min(len(text), remaining) + 2

    for block in blocks:
        if block.block_type in priority_types:
            add_block(block)
    for block in blocks:
        if block.block_type == "paragraph":
            add_block(block)
        if total >= GLOSSARY_TEXT_LIMIT:
            break

    return "\n\n".join(selected)


def glossary_text(db: Session, task_id: str) -> str:
    terms = db.query(GlossaryTerm).filter(GlossaryTerm.task_id == task_id).order_by(GlossaryTerm.source_term).all()
    return "\n".join(f"- {term.source_term} => {term.target_term} ({term.term_type})" for term in terms)


def fallback_candidate_terms(db: Session, task_id: str) -> list[GlossaryTerm]:
    blocks = db.query(TranslationBlock).filter(TranslationBlock.task_id == task_id).all()
    counter: Counter[str] = Counter()
    for block in blocks:
        text = _strip_latex_noise(block.source_text)
        for phrase in _candidate_phrases(text):
            if _is_useful_candidate(phrase):
                counter[phrase] += 1
    terms: list[GlossaryTerm] = []
    for phrase, freq in counter.most_common(20):
        term = GlossaryTerm(
            task_id=task_id,
            source_term=phrase,
            target_term=phrase,
            term_type="technical_term",
            frequency=freq,
            context=FALLBACK_CONTEXT,
            is_locked=False,
        )
        db.add(term)
        terms.append(term)
    db.commit()
    return terms


def _strip_latex_noise(text: str) -> str:
    text = re.sub(r"@@LATEX_PLACEHOLDER_\d+@@", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[^A-Za-z0-9+\\-/ ]+", " ", text)
    return re.sub(r"\s+", " ", text)


def _candidate_phrases(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9]*(?:[-+][A-Za-z0-9]+)*\b", text):
        value = match.group(0)
        if len(value) > 2:
            candidates.append(value)
    words = re.findall(r"[A-Za-z][A-Za-z0-9+\\-/]*", text)
    for size in (4, 3, 2):
        for i in range(len(words) - size + 1):
            phrase_words = words[i : i + size]
            phrase = " ".join(phrase_words)
            candidates.append(phrase)
    return candidates


def _is_useful_candidate(phrase: str) -> bool:
    normalized = phrase.strip(" -/").lower()
    if len(normalized) < 5 or len(normalized) > 80:
        return False
    words = normalized.split()
    if not words:
        return False
    if words[0] in STOPWORDS or words[-1] in STOPWORDS:
        return False
    if all(word in STOPWORDS for word in words):
        return False
    if len(words) == 1:
        return bool(re.search(r"[A-Z0-9]", phrase)) and len(phrase) >= 3
    meaningful = [word for word in words if word not in STOPWORDS]
    return len(meaningful) >= 2
