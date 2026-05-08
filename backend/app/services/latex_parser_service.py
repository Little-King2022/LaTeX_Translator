import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


PROTECTED_COMMANDS = [
    "label",
    "ref",
    "eqref",
    "autoref",
    "cref",
    "Cref",
    "cite",
    "citep",
    "citet",
    "bibliography",
    "bibliographystyle",
    "includegraphics",
    "input",
    "include",
    "url",
    "href",
]
SKIP_ENVS = ["equation", "align", "gather", "multline", "algorithm", "lstlisting", "verbatim", "tikzpicture"]
TRANSLATABLE_ENVS = ["abstract", "highlights"]
TRANSLATABLE_COMMANDS = ["title", "section", "subsection", "subsubsection", "paragraph", "caption"]


@dataclass
class ParsedBlock:
    id: str
    file_path: str
    block_index: int
    block_type: str
    source_text: str
    protected_text: str


def detect_main_tex(source_dir: Path) -> list[str]:
    candidates: list[tuple[int, str]] = []
    priorities = {"main.tex": 0, "paper.tex": 1, "manuscript.tex": 2, "article.tex": 3}
    for tex in source_dir.rglob("*.tex"):
        rel = tex.relative_to(source_dir).as_posix()
        try:
            text = tex.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        text = strip_latex_comments(text)
        has_class = "\\documentclass" in text
        has_doc = "\\begin{document}" in text and "\\end{document}" in text
        if has_class and has_doc:
            score = priorities.get(tex.name, 4)
            candidates.append((score, rel))
        elif has_class:
            candidates.append((10, rel))
    return [rel for _, rel in sorted(candidates, key=lambda item: (item[0], item[1]))]


def extract_blocks(source_dir: Path) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    for tex in sorted(source_dir.rglob("*.tex")):
        rel = tex.relative_to(source_dir).as_posix()
        text = tex.read_text(encoding="utf-8", errors="ignore")
        blocks.extend(_extract_file_blocks(rel, text, len(blocks)))
    return blocks


def _extract_file_blocks(file_path: str, text: str, start_index: int) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    seen_spans: list[tuple[int, int]] = []
    text = strip_latex_comments(text)

    for env in TRANSLATABLE_ENVS:
        for match in re.finditer(rf"\\begin\{{{env}\}}(?P<body>.*?)\\end\{{{env}\}}", text, flags=re.S):
            source = match.group("body").strip()
            if _worth_translating(source):
                seen_spans.append(match.span(0))
                blocks.append(_make_block(file_path, start_index + len(blocks), env, source))

    command_pattern = "|".join(re.escape(cmd) for cmd in TRANSLATABLE_COMMANDS)
    for match in re.finditer(rf"\\(?P<cmd>{command_pattern})\*?(?:\[[^\]]*\])?\{{(?P<body>(?:[^{{}}]|\{{[^{{}}]*\}})*)\}}", text, flags=re.S):
        source = match.group("body").strip()
        if _worth_translating(source):
            seen_spans.append(match.span(0))
            blocks.append(_make_block(file_path, start_index + len(blocks), match.group("cmd"), source))

    masked = _mask_spans(text, seen_spans)
    masked = _mask_skip_envs(masked)
    for para in re.split(r"\n\s*\n", masked):
        candidate = para.strip()
        if _worth_translating(candidate) and _is_translatable_paragraph(candidate):
            blocks.append(_make_block(file_path, start_index + len(blocks), "paragraph", candidate))
    return blocks


def _make_block(file_path: str, index: int, block_type: str, protected_text: str) -> ParsedBlock:
    source_text = protected_text
    protected_text, _ = protect_latex_with_map(source_text)
    digest = hashlib.sha1(f"{file_path}:{index}:{source_text}".encode("utf-8")).hexdigest()[:10]
    return ParsedBlock(
        id=f"{digest}-{index}",
        file_path=file_path,
        block_index=index,
        block_type=block_type,
        source_text=source_text,
        protected_text=protected_text,
    )


def protect_latex(text: str) -> str:
    protected, _ = protect_latex_with_map(text)
    return protected


def strip_latex_comments(text: str) -> str:
    return "\n".join(_strip_latex_comment_from_line(line) for line in text.splitlines())


def _strip_latex_comment_from_line(line: str) -> str:
    for index, char in enumerate(line):
        if char == "%" and not _is_escaped_percent(line, index):
            return line[:index].rstrip()
    return line


def _is_escaped_percent(line: str, index: int) -> bool:
    if index > 0 and line[index - 1] == "/":
        return True
    slash_count = 0
    cursor = index - 1
    while cursor >= 0 and line[cursor] == "\\":
        slash_count += 1
        cursor -= 1
    return slash_count % 2 == 1


def protect_latex_with_map(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    counter = 0

    def replace_patterns(source: str, patterns: list[str], flags: int = 0) -> str:
        nonlocal counter

        def repl(match: re.Match[str]) -> str:
            nonlocal counter
            counter += 1
            placeholder = f"@@LATEX_PLACEHOLDER_{counter:04d}@@"
            mapping[placeholder] = match.group(0)
            return placeholder

        result = source
        for pattern in patterns:
            result = re.sub(pattern, repl, result, flags=flags)
        return result

    protected = replace_patterns(
        text,
        [
            r"\$\$.*?\$\$",
            r"\$[^$\n]*(?:\\.[^$\n]*)*\$",
            r"\\\(.*?\\\)",
            r"\\\[.*?\\\]",
        ],
        flags=re.S,
    )
    for env in SKIP_ENVS:
        protected = replace_patterns(protected, [rf"\\begin\{{{env}\*?\}}.*?\\end\{{{env}\*?\}}"], flags=re.S)
    protected = replace_patterns(protected, [r"\\item\b"])
    for cmd in PROTECTED_COMMANDS:
        protected = replace_patterns(protected, [rf"\\{cmd}\*?(?:\[[^\]]*\])?\{{(?:[^{{}}]|\{{[^{{}}]*\}})*\}}"], flags=re.S)
    return protected, mapping


def restore_placeholders(translated: str, source: str) -> str:
    _, source_map = protect_latex_with_map(source)
    restored = translated
    for placeholder, original in source_map.items():
        restored = restored.replace(placeholder, original)
    return restored


def normalize_placeholders(translated: str, source: str) -> str:
    _, source_map = protect_latex_with_map(source)
    normalized = translated
    for placeholder, original in source_map.items():
        if placeholder in normalized:
            continue
        if original in normalized:
            normalized = normalized.replace(original, placeholder, 1)
    return normalized


def placeholder_count(text: str) -> int:
    return len(re.findall(r"@@LATEX_PLACEHOLDER_\d{4}@@", text))


def clean_llm_output(text: str) -> str:
    cleaned = text.strip()
    cleaned = _strip_leaked_thinking(cleaned)
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    prefixes = ["以下是翻译结果：", "翻译结果：", "译文："]
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s+", "", cleaned)
    return cleaned


def _strip_leaked_thinking(text: str) -> str:
    """Strip LLM 'thinking out loud' leaked into translation output.

    Removes meta-instruction sentences (e.g. '译为"response"' or '保存所有命令。')
    that LLMs may emit before the actual translation.
    Strips thinking sentences from the start of the text repeatedly until
    real translation content is reached.
    """
    # Strip leading whitespace first so patterns don't miss due to leading \n
    text = text.lstrip()
    if not text:
        return text

    thinking_sentence = re.compile(
        r'^.{0,5}["\u201c].{1,40}["\u201d]\s*译为[^。；]*[。；]\s*'
        r'|^.{0,5}译为.{0,5}["\u201c][^。；]*[。；]\s*'
        r'|^.{0,6}保存.{0,8}命令[。；]\s*'
        r'|^.{0,6}(注意|确保|务必|不要|请|必须)\s*(保留|修改|翻译|输出|使用|遵守)[^。；]*[。；]\s*'
        r'|^.{0,4}(好的|以下|下面|首先|接下来|然后|现在)\s*(，|。|,|\.)\s*我将[^。；]*[。；]\s*'
    )
    max_iter = 10
    for _ in range(max_iter):
        m = thinking_sentence.match(text)
        if not m:
            break
        text = text[m.end():].lstrip()

    # If everything was stripped (pure thinking output), return original
    # so validate_translation can properly detect the issue and trigger retry.
    if not text.strip():
        return text
    return text


def validate_translation(source_protected: str, translated: str) -> str | None:
    if not translated.strip():
        return "LLM returned empty output"
    if "```" in translated:
        return "LLM returned Markdown code fence"
    source_placeholders = set(re.findall(r"@@LATEX_PLACEHOLDER_\d{4}@@", source_protected))
    translated_placeholders = set(re.findall(r"@@LATEX_PLACEHOLDER_\d{4}@@", translated))
    missing = source_placeholders - translated_placeholders
    if missing:
        return f"Missing placeholders: {', '.join(sorted(missing))}"
    return None


def apply_translations(source_dir: Path, translated_dir: Path, translations: dict[str, list[tuple[str, str, str]]]) -> None:
    for file_path, replacements in translations.items():
        target = translated_dir / file_path
        text = target.read_text(encoding="utf-8", errors="ignore")
        for source, translated, block_type in replacements:
            if block_type in TRANSLATABLE_COMMANDS:
                text = _replace_command_body_once(text, block_type, source, translated)
            else:
                text = text.replace(source, translated, 1)
        target.write_text(text, encoding="utf-8")


def _replace_command_body_once(text: str, command: str, source: str, translated: str) -> str:
    pattern = re.compile(
        rf"(\\{re.escape(command)}\*?(?:\[[^\]]*\])?\{{)(?P<body>(?:[^{{}}]|\{{[^{{}}]*\}})*)(\}})",
        flags=re.S,
    )
    for match in pattern.finditer(text):
        if match.group("body").strip() != source.strip():
            continue
        return text[: match.start("body")] + translated + text[match.end("body") :]
    return text.replace(source, translated, 1)


def ensure_ctex(main_file: Path, zh_main_file: Path) -> None:
    text = main_file.read_text(encoding="utf-8", errors="ignore")
    if "\\usepackage" in text and "ctex" in text:
        zh_main_file.write_text(text, encoding="utf-8")
        return
    match = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", text)
    if match:
        insert_at = match.end()
        text = text[:insert_at] + "\n\\usepackage[UTF8]{ctex}" + text[insert_at:]
    zh_main_file.write_text(text, encoding="utf-8")


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


def _mask_skip_envs(text: str) -> str:
    masked = text
    for env in SKIP_ENVS + ["figure", "table"]:
        masked = re.sub(rf"\\begin\{{{env}\*?\}}.*?\\end\{{{env}\*?\}}", " ", masked, flags=re.S)
    return masked


def _worth_translating(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 8:
        return False
    return bool(re.search(r"[A-Za-z]{3,}", stripped))


def _is_translatable_paragraph(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if not stripped.startswith("\\"):
        return True

    probe = _strip_paragraph_prefix_commands(stripped)
    if not probe:
        return False
    if not probe.startswith("\\"):
        return _worth_translating(probe)

    return bool(
        re.match(
            r"\\(?:textbf|textit|emph|texttt|textsc|underline)\*?(?:\[[^\]]*\])?\{",
            probe,
        )
    )


def _strip_paragraph_prefix_commands(text: str) -> str:
    probe = text.lstrip()
    prefix_pattern = re.compile(
        r"^(?:"
        r"\\par\b"
        r"|\\(?:smallskip|medskip|bigskip|noindent|indent)\b"
        r"|\\vspace\*?(?:\[[^\]]*\])?\{[^{}]*\}"
        r"|\\hspace\*?(?:\[[^\]]*\])?\{[^{}]*\}"
        r")\s*",
        flags=re.S,
    )
    while True:
        match = prefix_pattern.match(probe)
        if not match:
            return probe
        probe = probe[match.end() :].lstrip()
