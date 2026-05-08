import json
import re
from collections import Counter
from pathlib import Path
from sqlalchemy.orm import Session

from app.models import GlossaryTerm, TranslationBlock
from app.services.latex_parser_service import clean_llm_output
from app.services.llm_client import LLMClient


TERM_TYPES = {"technical_term", "model_name", "dataset_name", "metric", "abbreviation", "do_not_translate"}
GLOSSARY_TEXT_LIMIT = 12000
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
    text = _build_glossary_source_text(blocks)
    prompt = """你是农业工程、计算机视觉、深度学习和作物表型分析领域的学术论文术语提取助手。

请从以下英文 LaTeX 论文文本中提取重要术语，并给出推荐中文译名。

要求：
1. 提取专业术语、算法名、模型名、数据集名、评价指标、缩写和不应翻译的专有名词；
2. 不要提取普通英语单词；
3. 不要修改 LaTeX 命令、公式、引用和标签；
4. 输出 JSON 数组；
5. 每个元素包含 source_term、target_term、term_type、context；
6. 对模型名、数据集名、缩写，如果建议保留英文，则 target_term 与 source_term 相同；
7. 不输出 Markdown，不输出解释。
8. 必须输出严格合法 JSON，所有键名和字符串必须使用双引号，不能有尾随逗号。
9. 最多输出 30 个最重要术语。

term_type 只能从以下值中选择：
technical_term, model_name, dataset_name, metric, abbreviation, do_not_translate
"""
    content = await client.chat(
        [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        top_p=config.top_p,
        stream=False,
    )
    _write_glossary_raw_log(task_id, content)
    parsed = parse_glossary_json(content)
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
            is_locked=term_type in {"model_name", "dataset_name", "abbreviation", "do_not_translate"},
        )
        db.add(term)
        terms.append(term)
        existing.add(source.lower())
    db.commit()
    return terms


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
