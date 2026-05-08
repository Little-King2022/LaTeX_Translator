# LaTeX LLM Translator Web App 开发方案

## 0. 当前项目交接状态（2026-05-08）

本节记录当前代码、Docker、任务和已知问题状态，供新 session 继续开发时优先阅读。下面内容优先级高于旧的“建议/推荐”文字，但不改变本文件后续的总体目标。

### 0.1 当前运行方式

项目根目录：

```text
/data2/jinchuanjing/LaTeX_Translator
```

Docker 服务当前使用：

```text
frontend: http://localhost:3000
backend:  http://localhost:18000
redis:    localhost:6379
```

`docker-compose.yml` 中后端端口是 `18000:8000`，不是最初方案里的 `8000:8000`。原因是宿主机 8000 曾被其他容器占用。

常用检查命令：

```bash
docker compose ps
curl --noproxy '*' http://127.0.0.1:18000/api/health
docker compose logs --tail=120 backend
```

注意：本机环境有代理时，`curl http://127.0.0.1:18000/...` 可能返回 502；排查本地 API 时使用 `--noproxy '*'`。

默认登录：

```text
username: admin
password: admin
```

### 0.2 已实现的主要功能

当前项目已经不是空架子，已实现 MVP 的大部分链路：

```text
FastAPI 后端
Vue 3 + Vite + Element Plus 前端
JWT 单用户登录
SQLite 持久化
LLM 配置保存、脱敏展示、测试连接
任务创建、zip 上传、解压、main.tex 识别
英文 PDF 自动编译
LaTeX block 提取与结构保护
术语提取与术语表 CRUD
按 block 调用 OpenAI-compatible LLM 翻译
中文项目生成、ctex 插入、中文 PDF 编译
PDF.js 中英文 PDF 并排预览与同步滚动
翻译 block 列表和手动编辑译文
Docker 部署
```

### 0.3 Docker / TeX Live 相关修复

后端 Dockerfile 已做缓存优化：

```dockerfile
# syntax=docker/dockerfile:1.7
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked ...
RUN --mount=type=cache,target=/root/.cache/pip ...
```

TeX Live 包已补充，解决过这些编译缺包问题：

```text
elsarticle.cls -> texlive-publishers
pzdr.tfm       -> texlive-fonts-recommended
siunitx.sty    -> texlive-science
中文支持       -> texlive-lang-chinese
```

前端 nginx 已放宽上传限制：

```nginx
client_max_body_size 1024m;
```

### 0.4 重要代码修复记录

#### LLM 与术语提取

- `backend/app/services/llm_client.py`
  - 增强 OpenAI-compatible 响应解析。
  - 如果 `message.content` 为空，会输出包含 `finish_reason`、`reasoning_content` 长度和 `usage` 的明确错误。

- `backend/app/services/glossary_service.py`
  - 术语提取输入缩小到标题、摘要、章节、caption 和部分正文。
  - 限制最多 30 个术语。
  - 增强 JSON 修复：去 Markdown fence、提取 JSON array、修复尾逗号、修复常见未加引号 key。
  - fallback 术语加入停用词过滤，避免 `of the`、`to the` 等噪声。

#### LaTeX parser

- `backend/app/services/latex_parser_service.py`
  - 翻译前保护公式、引用、label、cite、ref、url、href、includegraphics 等命令。
  - 已修复注释提取问题：`%` 注释不会进入 block；`\%` 和用户提到的 `/%` 不触发注释剥离。
  - `clean_llm_output()` 已移除 LLM 可能输出的 Markdown 标题前缀，如 `# 引言`。
  - 新增/使用 `normalize_placeholders()`，允许模型把 placeholder 还原成原始 LaTeX 命令时先归一回 placeholder 再校验，避免误报 `Missing placeholders`。

#### 翻译后台任务和卡死问题

- `backend/app/workers/tasks.py`
  - LLM 翻译并发由 LLM 配置字段 `llm_concurrency` 控制。
  - 每次 LLM 请求外层增加 `asyncio.wait_for(..., timeout=config.timeout)`，避免单个请求无限挂起。
  - `parse_blocks()` 已改为补齐缺失 block：不会因为数据库里已有 block 就直接跳过；会按 `file_path + block_type + source_text` 判断是否新增。
  - 修复过旧任务漏提长正文的问题，当前任务因此从 88 个 block 补齐到 153 个 block。
  - 批量翻译曾因所有协程先打开 DB Session 再等待 semaphore，导致 SQLAlchemy 连接池耗尽；已修复为先等待并发名额，再打开 Session。

- `backend/app/workers/runner.py`
  - 新增独立后台线程 runner。
  - API 不再用 `asyncio.create_task()` 在 uvicorn 主事件循环上直接跑长翻译任务。
  - 同一个后台任务 key 会去重，重复点击可能返回 `{"queued": false}`，表示已有同任务后台线程在跑。

- `backend/app/main.py`
  - 启动时自动恢复中断任务：把遗留 `TranslationBlock.status == "translating"` 复位为 `pending`，把 `Task.status == "translating"` 复位为 `waiting_glossary_review`。

- `backend/app/api/tasks.py`
  - 上传、编译、术语提取、开始翻译、重新编译、重译 block 统一通过 `run_background()` 入后台线程。
  - `/blocks` 轮询不再每次调用 `parse_blocks()`，只有 `total_blocks == 0` 时才初次解析，避免前端 3.5 秒轮询造成 parser 压力。

### 0.5 当前数据库和任务状态

当前 LLM 配置：

```text
id: 1
name: deepseek v4 flash
base_url: https://api.deepseek.com
model: deepseek-v4-flash
timeout: 120
llm_concurrency: 1
```

当前主要任务：

```text
task_id: 67f84357-7a5b-42e0-bb37-cfaff003406c
name: LaTeX 翻译任务 2026/5/7 23:43:21
main_tex_path: RBNet.tex
status: waiting_glossary_review / translating 之间可能随后台任务变化
total_blocks: 153
completed_blocks: 最近检查为 123
pending_blocks: 最近检查为 29
translating_blocks: 最近检查为 1
failed_blocks: 0
original_pdf: workspace/tasks/67f84357-7a5b-42e0-bb37-cfaff003406c/output/original.pdf
translated_pdf: workspace/tasks/67f84357-7a5b-42e0-bb37-cfaff003406c/output/translated.pdf
translated_project_zip: workspace/tasks/67f84357-7a5b-42e0-bb37-cfaff003406c/output/translated_project.zip
```

注意：当前 `translated.pdf` 已能编译生成，但它是在补齐 65 个缺失正文 block 之前生成的旧结果，因此 PDF 中仍可能有大量英文。需要等剩余 pending block 全部翻译完成后，重新生成中文项目并重新编译中文 PDF。

另一个任务：

```text
task_id: 190fc29c-d6bd-4b95-b81b-334172535518
status: failed
main_tex_path: main.tex
error: Main TeX file not found: main_zh.tex
blocks: 0 / 79
```

这个任务不是当前主线，除非用户明确切换，否则优先处理 `67f84357-...`。

### 0.6 当前最重要的下一步

1. 确认后端仍健康：

```bash
curl --noproxy '*' http://127.0.0.1:18000/api/health
```

2. 查看主任务 block 进度：

```bash
docker compose exec backend python -c "from app.db.database import SessionLocal; from app.models import Task, TranslationBlock; tid='67f84357-7a5b-42e0-bb37-cfaff003406c'; db=SessionLocal(); t=db.get(Task, tid); print(t.status, t.translated_blocks, t.total_blocks, t.failed_blocks); print('pending', db.query(TranslationBlock).filter(TranslationBlock.task_id==tid, TranslationBlock.status=='pending').count(), 'translating', db.query(TranslationBlock).filter(TranslationBlock.task_id==tid, TranslationBlock.status=='translating').count(), 'completed', db.query(TranslationBlock).filter(TranslationBlock.task_id==tid, TranslationBlock.status=='completed').count()); db.close()"
```

3. 如果还有 pending block，点击页面“确认术语并翻译”或调用 `/start-translation` 继续。现在并发为 1，速度慢但更稳定。

4. 如果 `queued: false`，表示同任务已有后台翻译线程在跑，不要重复启动。等几分钟后看 completed/pending 是否变化。

5. 所有 block 完成后，系统会自动生成 translated 项目并编译中文 PDF。若没有自动编译，可点击“重新编译中文”。

### 0.7 已知风险和注意事项

- DeepSeek 长正文 block 可能响应很慢。当前并发设为 1 是为了稳定，不要轻易调回 5。
- 不要把整篇论文一次性发给 LLM；必须保持 block 翻译。
- 不要直接覆盖 `source/`，只写 `translated/`。
- `.bib` 不翻译。
- 如果用户说“后端挂了”，先看是否是 SQLAlchemy 连接池、后台线程、或代理导致的假 502。
- 本环境 `curl` 可能走代理，访问本机端口时使用 `--noproxy '*'`。
- 当前代码修复后还没有做完整单元测试，主要通过 Docker 内运行和实际任务验证。

---

## 1. 项目目标

开发一个运行在 Linux 服务器上的单用户 Web App，用于将英文 LaTeX 论文项目翻译为中文，并自动编译英文版 PDF 和中文版 PDF。系统需要支持多任务管理、自定义 OpenAI-compatible LLM API、术语库自动提取与人工修订、翻译结果审阅，以及中英文 PDF 并排对照显示和同步滚动。

本项目的核心目标不是普通 PDF 翻译，而是 **LaTeX 源码级翻译**：

```text
上传英文 LaTeX 项目 zip
        ↓
识别 main.tex、子文件、bib、图片资源
        ↓
编译原始英文 PDF
        ↓
解析 LaTeX 源码，保护公式、引用、标签、命令
        ↓
使用大语言模型提取术语库
        ↓
允许用户编辑术语库
        ↓
按段落/章节翻译 LaTeX 正文
        ↓
生成中文 LaTeX 项目
        ↓
编译中文 PDF
        ↓
Web 中并排显示英文 PDF 和中文 PDF
```

---

## 2. 总体技术栈

### 2.1 后端

推荐使用：

```text
Python 3
FastAPI
SQLite
Redis + RQ 或 Celery
Pydantic
SQLAlchemy
httpx
latexmk
TeX Live
```

说明：

- FastAPI 负责 Web API。
- SQLite 足够支持单用户和多任务管理。
- Redis + RQ/Celery 用于后台任务队列，避免翻译和编译阻塞 Web 请求。
- TeX Live / latexmk 用于自动编译 PDF。
- httpx 用于调用 OpenAI-compatible LLM API。
- 所有任务文件保存在服务器本地 workspace 中。

### 2.2 前端

推荐使用：

```text
Vue 3
Vite
JavaScript 或 TypeScript
Element Plus / Naive UI / Ant Design Vue
PDF.js
```

说明：

- 前端界面要求简洁、美观、偏科研工具风格。
- PDF 预览使用 PDF.js。
- 英文 PDF 和中文 PDF 并排显示。
- 支持同步滚动、页码跳转、缩放。
- 支持任务状态实时刷新，可使用 polling 或 WebSocket。

---

## 3. 系统模块划分

建议项目结构：

```text
latex-translator-app/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── services/
│   │   │   ├── latex_project_service.py
│   │   │   ├── latex_parser_service.py
│   │   │   ├── llm_client.py
│   │   │   ├── glossary_service.py
│   │   │   ├── translation_service.py
│   │   │   ├── compile_service.py
│   │   │   └── pdf_service.py
│   │   ├── workers/
│   │   └── utils/
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── views/
│   │   ├── components/
│   │   ├── stores/
│   │   └── router/
│   ├── package.json
│   └── vite.config.js
│
├── workspace/
│   └── tasks/
│
├── docker-compose.yml
└── README.md
```

---

## 4. 核心功能需求

## 4.1 单用户登录

系统只需要支持单用户登录，不需要复杂的权限管理。

### 功能要求

- 支持用户名和密码登录。
- 登录后获取 session 或 JWT。
- 所有任务均属于当前唯一用户。
- 不需要用户注册功能。
- 用户名、密码哈希、JWT secret 可通过 `.env` 配置。

### 推荐配置

```env
APP_USERNAME=admin
APP_PASSWORD_HASH=...
JWT_SECRET_KEY=...
SESSION_EXPIRE_HOURS=24
```

### 注意事项

- 不要在数据库中保存明文密码。
- 不需要角色系统。
- 不需要多用户隔离。
- 但需要防止未登录访问任务文件和 PDF 文件。

---

## 4.2 LLM API 自定义配置

系统必须支持用户在 Web 页面中配置 OpenAI-compatible LLM API。

### 配置项

```text
base_url
api_key
model
temperature
top_p
max_tokens
timeout
stream
```

### 示例

```text
base_url: http://127.0.0.1:11434/v1
api_key: ollama
model: qwen2.5:14b
```

或：

```text
base_url: http://127.0.0.1:8000/v1
api_key: EMPTY
model: Qwen2.5-32B-Instruct
```

### 功能要求

- 提供 LLM 配置页面。
- 支持保存配置。
- 支持“测试连接”按钮。
- 支持查看当前模型配置。
- API Key 在前端显示时需要脱敏。
- 后端调用 LLM 时统一通过 `llm_client.py`。

### 后端 LLM Client 要求

实现一个兼容 OpenAI Chat Completions 格式的客户端：

```python
class LLMClient:
    def __init__(self, base_url, api_key, model, timeout):
        ...

    async def chat(self, messages, temperature=0.2, max_tokens=4096):
        ...
```

接口路径优先使用：

```text
/v1/chat/completions
```

不要把具体模型供应商写死，所有模型都按 OpenAI-compatible API 调用。

---

## 4.3 多任务管理

系统需要支持多个 LaTeX 翻译任务并行存在。

### 任务状态

任务状态至少包括：

```text
created
uploaded
extracting
waiting_glossary_review
translating
compiling_original
compiling_translated
completed
failed
cancelled
```

### 任务列表页

需要显示：

```text
任务名称
上传时间
当前状态
翻译进度
编译状态
LLM 模型
是否已有英文 PDF
是否已有中文 PDF
操作按钮
```

### 操作按钮

```text
查看详情
开始术语提取
确认术语库并开始翻译
重新翻译
重新编译
下载英文 PDF
下载中文 PDF
下载中文 LaTeX 项目
删除任务
```

### 任务数据目录

每个任务独立一个目录：

```text
workspace/tasks/{task_id}/
├── upload/
│   └── original.zip
├── source/
│   ├── main.tex
│   ├── sections/
│   ├── figures/
│   └── refs.bib
├── translated/
│   ├── main_zh.tex
│   ├── sections/
│   ├── figures/
│   └── refs.bib
├── build_original/
├── build_translated/
├── output/
│   ├── original.pdf
│   ├── translated.pdf
│   └── translated_project.zip
├── logs/
│   ├── extract_terms.log
│   ├── translate.log
│   ├── compile_original.log
│   └── compile_translated.log
└── metadata.json
```

---

## 4.4 上传 LaTeX 项目

用户上传一个 `.zip` 文件，里面包含完整 LaTeX 项目。

### 上传要求

支持：

```text
main.tex
多个 section 子文件
图片文件
bib 文件
cls/sty 文件
latexmkrc
```

### 上传后的处理

后端需要：

1. 保存 zip。
2. 解压到任务目录。
3. 扫描 `.tex` 文件。
4. 尝试识别主文件。
5. 如果存在多个候选主文件，前端让用户手动选择。
6. 保存主文件路径。
7. 尝试编译英文 PDF。

### 主文件识别规则

优先查找包含以下内容的 `.tex` 文件：

```latex
\documentclass
\begin{document}
\end{document}
```

如果多个文件匹配，按以下优先级排序：

```text
main.tex
paper.tex
manuscript.tex
article.tex
*.tex 中包含 \documentclass 的文件
```

---

## 4.5 编译英文 PDF 和中文 PDF

系统在翻译完成后，需要自动编译：

```text
原始英文 PDF
中文版 PDF
```

### 编译命令

优先使用：

```bash
latexmk -xelatex -interaction=nonstopmode -file-line-error -halt-on-error main.tex
```

中文版使用：

```bash
latexmk -xelatex -interaction=nonstopmode -file-line-error -halt-on-error main_zh.tex
```

### 编译要求

- 编译过程必须记录日志。
- 编译失败时，前端需要展示错误日志。
- 支持用户手动点击“重新编译”。
- 编译成功后，将 PDF 复制到 `output/` 目录。
- 英文 PDF 和中文 PDF 都需要可下载。
- 中文 PDF 编译建议默认使用 XeLaTeX。

### 中文 LaTeX 处理

对于中文项目，需要确保主文件支持中文。可采用以下策略：

如果原始文档是：

```latex
\documentclass[preprint,12pt]{elsarticle}
```

则中文主文件可自动加入：

```latex
\usepackage[UTF8]{ctex}
```

插入位置应在 `\documentclass` 之后、`\begin{document}` 之前。

不要强行把所有模板改成 `ctexart`，因为用户可能需要保留期刊模板。

### 编译安全

由于用户上传 LaTeX 项目，编译命令必须限制在任务目录中执行。

要求：

- 不允许任意 shell 命令注入。
- 编译命令参数固定。
- 不允许用户自定义编译命令作为 shell 字符串直接执行。
- 设置超时时间，例如 120 秒或 300 秒。
- 可以通过 Docker 隔离编译环境。
- 后续可以增加禁用 `--shell-escape` 的策略。

---

## 4.6 LaTeX 源码解析与保护

这是本项目最核心的模块。

目标：只翻译自然语言，不破坏 LaTeX 结构。

### 需要保护的内容

必须保持不变：

```latex
\label{}
\ref{}
\eqref{}
\autoref{}
\cref{}
\Cref{}
\cite{}
\citep{}
\citet{}
\bibliography{}
\bibliographystyle{}
\includegraphics{}
\input{}
\include{}
\url{}
\href{}
```

必须保持公式不变：

```latex
$...$
$$...$$
\(...\)
\[...\]
\begin{equation}...\end{equation}
\begin{align}...\end{align}
\begin{gather}...\end{gather}
\begin{multline}...\end{multline}
```

建议默认整体跳过的环境：

```text
equation
align
gather
multline
algorithm
lstlisting
verbatim
tikzpicture
figure
table
```

但 figure/table 内部的 caption 可以单独提取翻译。

### 可翻译内容

需要翻译：

```latex
\title{...}
\begin{abstract} ... \end{abstract}
\section{...}
\subsection{...}
\subsubsection{...}
\paragraph{...}
正文自然段
\caption{...}
表格中的英文表头和说明文字，可作为后续增强功能
```

### 解析策略

不要直接把整个 `.tex` 文件丢给 LLM。

推荐流程：

```text
读取 tex 文件
        ↓
识别并保护 LaTeX 命令、公式、引用、标签
        ↓
按自然段切分
        ↓
对可翻译块生成 block_id
        ↓
调用 LLM 翻译每个 block
        ↓
恢复占位符
        ↓
写回中文 tex 文件
```

### 占位符示例

将需要保护的 LaTeX 内容替换成：

```text
@@LATEX_PLACEHOLDER_0001@@
@@LATEX_PLACEHOLDER_0002@@
```

翻译完成后再恢复。

### 块结构

建议定义：

```json
{
  "block_id": "sec-intro-p0003",
  "file_path": "sections/introduction.tex",
  "block_type": "paragraph",
  "source_text": "...",
  "protected_text": "...",
  "translated_text": "...",
  "status": "pending"
}
```

block_type 包括：

```text
title
abstract
section
subsection
paragraph
caption
table_text
```

---

## 4.7 术语库自动提取与人工修改

系统需要在翻译过程中自动提取术语库，并支持用户手动修改。

推荐采用两阶段流程：

```text
上传 LaTeX 项目
        ↓
解析可翻译文本
        ↓
LLM 自动提取候选术语库
        ↓
用户在 Web 页面中编辑术语库
        ↓
确认术语库
        ↓
正式翻译
```

这样比“边翻译边提取”更稳定，也方便用户在翻译前统一术语。

### 术语提取内容

LLM 需要从论文中提取：

```text
专业术语
模型名称
算法名称
数据集名称
评价指标
农业领域术语
计算机视觉术语
缩写及其全称
不应翻译的专有名词
```

### 术语库字段

数据库表建议：

```text
id
task_id
source_term
target_term
term_type
frequency
context
is_locked
created_at
updated_at
```

term_type 可选：

```text
technical_term
model_name
dataset_name
metric
abbreviation
do_not_translate
custom
```

### 前端术语库页面

需要支持：

```text
查看术语
搜索术语
添加术语
删除术语
修改中文译名
锁定术语
标记为“不翻译”
批量导入
批量导出 JSON / CSV
```

### 术语库示例

```json
[
  {
    "source_term": "plant phenotyping",
    "target_term": "植物表型分析",
    "term_type": "technical_term",
    "is_locked": true
  },
  {
    "source_term": "semantic segmentation",
    "target_term": "语义分割",
    "term_type": "technical_term",
    "is_locked": true
  },
  {
    "source_term": "Mask2Former",
    "target_term": "Mask2Former",
    "term_type": "model_name",
    "is_locked": true
  }
]
```

---

## 4.8 LLM Prompt 设计

### 术语提取 Prompt

```text
你是农业工程、计算机视觉、深度学习和作物表型分析领域的学术论文术语提取助手。

请从以下英文 LaTeX 论文文本中提取重要术语，并给出推荐中文译名。

要求：
1. 提取专业术语、算法名、模型名、数据集名、评价指标、缩写和不应翻译的专有名词；
2. 不要提取普通英语单词；
3. 不要修改 LaTeX 命令、公式、引用和标签；
4. 输出 JSON 数组；
5. 每个元素包含 source_term、target_term、term_type、context；
6. 对模型名、数据集名、缩写，如果建议保留英文，则 target_term 与 source_term 相同；
7. 不输出 Markdown，不输出解释。

term_type 只能从以下值中选择：
technical_term, model_name, dataset_name, metric, abbreviation, do_not_translate
```

### 翻译 Prompt

```text
你是农业工程、计算机视觉、深度学习和作物表型分析领域的英文学术论文翻译助手。

请将以下英文 LaTeX 论文内容翻译为中文。

必须遵守：
1. 保留所有 LaTeX 命令、环境、数学公式、引用命令、标签和占位符不变；
2. 不修改任何形如 @@LATEX_PLACEHOLDER_0001@@ 的占位符；
3. 不修改 \cite{}、\ref{}、\label{}、\autoref{}、\cref{}、\Cref{}、\url{}、\href{} 等命令；
4. 不翻译变量名、模型名、数据集名、文件路径和代码片段；
5. 中文表达应符合正式学术论文风格；
6. 严格使用给定术语库；
7. 不添加解释；
8. 不输出 Markdown；
9. 只输出翻译后的 LaTeX 内容。

术语库：
{glossary}

待翻译内容：
{text}
```

### 翻译质量检查 Prompt

可作为后续增强功能：

```text
请检查以下 LaTeX 翻译是否存在问题：
1. LaTeX 命令是否被破坏；
2. 占位符是否完整保留；
3. 术语是否与术语库一致；
4. 是否有明显漏译；
5. 中文是否存在不自然表达。

只输出 JSON。
```

---

## 4.9 翻译过程控制

### 翻译流程

```text
创建任务
上传 zip
解压项目
识别 main.tex
编译英文 PDF
解析 tex 文件
提取可翻译 block
提取术语库
等待用户确认术语库
按 block 调用 LLM 翻译
生成 translated tex 项目
插入中文支持包
编译中文 PDF
生成对照预览
```

### 进度计算

任务进度建议基于 block 数量：

```text
translated_blocks / total_blocks
```

前端显示：

```text
当前章节
当前文件
当前段落编号
总段落数
已完成段落数
失败段落数
当前 LLM 调用状态
```

### 失败重试

每个 block 翻译失败时：

- 自动重试 2 次。
- 仍失败则标记为 failed。
- 任务不一定整体终止。
- 翻译完成后允许用户单独重试失败 block。

### 断点续传

任务中断后，重新启动 worker 时应从数据库中读取 block 状态，只翻译未完成 block。

---

## 4.10 PDF 并排显示和同步滚动

前端需要实现中英文 PDF 并排对照。

### 页面布局

```text
顶部：任务标题、状态、缩放、页码跳转、重新编译按钮
左侧：英文 PDF
右侧：中文 PDF
底部或侧栏：编译日志 / 翻译日志 / 术语库入口
```

### PDF 渲染

使用 PDF.js 渲染两个 PDF。

功能要求：

```text
并排显示
同步滚动
页码同步
缩放同步
支持跳转页码
支持下载 PDF
```

### 同步滚动策略

基础版：

```text
左侧滚动时，右侧按滚动比例同步
右侧滚动时，左侧按滚动比例同步
防止递归触发滚动事件
```

伪代码：

```javascript
let syncing = false;

function syncScroll(source, target) {
  if (syncing) return;
  syncing = true;

  const ratio = source.scrollTop / (source.scrollHeight - source.clientHeight);
  target.scrollTop = ratio * (target.scrollHeight - target.clientHeight);

  requestAnimationFrame(() => {
    syncing = false;
  });
}
```

增强版：

```text
按页码同步
根据当前可视区域中心点判断当前页
中文 PDF 跳转到相同页码
```

由于中文翻译后分页可能变化，基础同步策略以滚动比例为主，页码同步作为辅助。

---

## 4.11 前端页面设计

### 页面 1：登录页

功能：

```text
用户名
密码
登录按钮
错误提示
```

风格：

```text
简洁
居中卡片
浅色背景
不要复杂动效
```

### 页面 2：任务列表页

功能：

```text
新建任务
上传 LaTeX zip
任务列表
任务状态
进度条
操作按钮
```

### 页面 3：任务详情页

包含多个 Tab：

```text
概览
术语库
翻译进度
PDF 对照
日志
文件下载
```

### 页面 4：LLM 配置页

功能：

```text
base_url
api_key
model
temperature
max_tokens
测试连接
保存配置
```

### 页面 5：术语库编辑页

功能：

```text
术语表格
搜索
新增
修改
删除
锁定
导入
导出
确认并开始翻译
```

### 页面 6：PDF 对照页

功能：

```text
英文 PDF 左侧显示
中文 PDF 右侧显示
同步滚动
缩放
页码跳转
下载
重新编译
```

---

## 5. 数据库设计

使用 SQLite 即可。

### users 表

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

### llm_configs 表

```sql
CREATE TABLE llm_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_key TEXT,
    model TEXT NOT NULL,
    temperature REAL DEFAULT 0.2,
    top_p REAL DEFAULT 1.0,
    max_tokens INTEGER DEFAULT 4096,
    timeout INTEGER DEFAULT 120,
    is_default INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### tasks 表

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    main_tex_path TEXT,
    source_dir TEXT NOT NULL,
    translated_dir TEXT,
    original_pdf_path TEXT,
    translated_pdf_path TEXT,
    total_blocks INTEGER DEFAULT 0,
    translated_blocks INTEGER DEFAULT 0,
    failed_blocks INTEGER DEFAULT 0,
    llm_config_id INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### translation_blocks 表

```sql
CREATE TABLE translation_blocks (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    block_type TEXT NOT NULL,
    source_text TEXT NOT NULL,
    protected_text TEXT,
    translated_text TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### glossary_terms 表

```sql
CREATE TABLE glossary_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL,
    term_type TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    context TEXT,
    is_locked INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### logs 表

```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

---

## 6. 后端 API 设计

### Auth

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

### LLM 配置

```text
GET    /api/llm-configs
POST   /api/llm-configs
PUT    /api/llm-configs/{id}
DELETE /api/llm-configs/{id}
POST   /api/llm-configs/{id}/test
```

### 任务管理

```text
GET    /api/tasks
POST   /api/tasks
GET    /api/tasks/{task_id}
DELETE /api/tasks/{task_id}
POST   /api/tasks/{task_id}/upload
POST   /api/tasks/{task_id}/detect-main
POST   /api/tasks/{task_id}/compile-original
POST   /api/tasks/{task_id}/extract-glossary
POST   /api/tasks/{task_id}/start-translation
POST   /api/tasks/{task_id}/compile-translated
POST   /api/tasks/{task_id}/retry-failed-blocks
POST   /api/tasks/{task_id}/cancel
```

### 术语库

```text
GET    /api/tasks/{task_id}/glossary
POST   /api/tasks/{task_id}/glossary
PUT    /api/tasks/{task_id}/glossary/{term_id}
DELETE /api/tasks/{task_id}/glossary/{term_id}
POST   /api/tasks/{task_id}/glossary/import
GET    /api/tasks/{task_id}/glossary/export
```

### 翻译块

```text
GET  /api/tasks/{task_id}/blocks
GET  /api/tasks/{task_id}/blocks/{block_id}
PUT  /api/tasks/{task_id}/blocks/{block_id}
POST /api/tasks/{task_id}/blocks/{block_id}/retranslate
```

### 文件和 PDF

```text
GET /api/tasks/{task_id}/pdf/original
GET /api/tasks/{task_id}/pdf/translated
GET /api/tasks/{task_id}/download/original-pdf
GET /api/tasks/{task_id}/download/translated-pdf
GET /api/tasks/{task_id}/download/translated-project
GET /api/tasks/{task_id}/logs
```

---

## 7. 关键实现细节

## 7.1 翻译文件生成策略

不要直接覆盖原始文件。

原始文件目录：

```text
source/
```

中文文件目录：

```text
translated/
```

生成中文项目时：

1. 完整复制原始项目到 `translated/`。
2. 对需要翻译的 `.tex` 文件进行替换。
3. 保留图片、bib、cls、sty 等文件。
4. 生成新的中文主文件，例如 `main_zh.tex`。
5. 如果原始 main.tex 中使用 `\input{sections/introduction}`，中文项目中应保持相同结构，但对应文件内容已经翻译。

## 7.2 不应翻译 bib 文件

默认不要翻译 `.bib` 文件。

原因：

- 参考文献格式容易被破坏。
- DOI、期刊名、作者名不应改变。
- 中文论文内部阅读时也可以保留英文参考文献。

后续可以增加“翻译参考文献标题”的可选功能，但 MVP 不做。

## 7.3 表格翻译策略

MVP 中可以先跳过复杂表格内容，只翻译：

```text
table caption
表格上方/下方说明文字
```

后续增强：

```text
翻译 tabular 中的纯文本表头
跳过数字、公式、变量名
```

## 7.4 Figure 处理策略

MVP 中：

- 不修改图片。
- 不翻译图片文件名。
- 只翻译 `\caption{}`。
- 保留 `\label{}`。

## 7.5 中文标点

翻译结果应使用中文标点，但 LaTeX 命令和公式附近不要引入异常空格。

例如：

```latex
As shown in \figref{fig:framework}, the proposed method...
```

可翻译为：

```latex
如 \figref{fig:framework} 所示，所提出的方法……
```

不要把 `\figref{}` 改成中文。

---

## 8. 质量检查

每个翻译块完成后，需要做基本检查。

### 检查项

```text
占位符数量是否一致
LaTeX 命令是否被删除
括号是否明显不匹配
是否输出了 Markdown 代码块
是否出现“以下是翻译结果”等多余文本
是否空输出
```

### 自动修复

如果模型输出 Markdown 代码块，需要自动去除代码块包裹。

如果占位符丢失，应重试该 block。

---

## 9. 日志与错误处理

系统应记录：

```text
任务状态变化
LLM 请求失败
LLM 响应异常
术语提取失败
翻译块失败
LaTeX 编译 stdout/stderr
文件操作错误
```

前端日志页面需要展示：

```text
时间
级别
模块
消息
```

错误信息要可读，尤其是 LaTeX 编译失败时，需要保留 `file:line:error` 信息。

---

## 10. Docker 部署

建议提供 `docker-compose.yml`：

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./workspace:/app/workspace
      - ./data:/app/data
    environment:
      - DATABASE_URL=sqlite:///app/data/app.db
    depends_on:
      - redis

  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend

  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
```

后续如果需要完整 LaTeX 编译环境，可以把 TeX Live 安装在 backend 镜像中，或单独做 compile worker 镜像。

---

## 11. MVP 开发顺序

请按以下顺序开发，不要一开始做过度复杂的功能。

### 阶段 A：基础框架

完成：

```text
FastAPI 后端
Vue 前端
登录功能
SQLite 初始化
任务列表
LLM 配置页面
测试 LLM 连接
```

验收：

```text
用户可以登录
用户可以保存 LLM 配置
用户可以测试 OpenAI-compatible API
```

### 阶段 B：任务上传与英文 PDF 编译

完成：

```text
创建任务
上传 zip
解压 LaTeX 项目
识别 main.tex
编译英文 PDF
前端显示编译日志
英文 PDF 可下载
```

验收：

```text
上传一个正常 LaTeX 项目后，可以得到原始英文 PDF
```

### 阶段 C：LaTeX 解析与术语库提取

完成：

```text
扫描 tex 文件
提取可翻译 block
保护 LaTeX 命令和公式
调用 LLM 提取术语
术语库页面展示
支持术语增删改查
```

验收：

```text
用户可以看到自动生成的术语库，并手动修改
```

### 阶段 D：正文翻译

完成：

```text
按 block 翻译
术语库注入 prompt
失败重试
断点续跑
生成 translated 项目
显示翻译进度
```

验收：

```text
用户确认术语库后，系统可以生成中文 tex 文件
LaTeX 命令、引用、标签未被破坏
```

### 阶段 E：中文 PDF 编译

完成：

```text
自动插入 ctex 支持
编译中文 PDF
保存编译日志
中文 PDF 下载
中文项目 zip 下载
```

验收：

```text
翻译完成后，可以得到中文版 PDF 和中文 LaTeX 项目
```

### 阶段 F：PDF 并排对照

完成：

```text
PDF.js 预览
英文 PDF 左侧
中文 PDF 右侧
同步滚动
缩放同步
页码跳转
```

验收：

```text
用户可以在 Web 中并排查看中英文 PDF，并对照翻译质量
```

---

## 12. 非目标功能

MVP 暂不实现：

```text
多用户权限管理
团队协作
在线编辑完整 LaTeX 项目
复杂版本管理
OCR
Word 导出
PDF 直接翻译
参考文献自动中文化
图片中文字翻译
公式语义解释
```

---

## 13. 验收标准

项目完成后，至少满足以下条件：

```text
1. 用户可以登录系统。
2. 用户可以配置 OpenAI-compatible LLM API。
3. 用户可以创建多个翻译任务。
4. 用户可以上传 LaTeX zip 项目。
5. 系统可以自动编译原始英文 PDF。
6. 系统可以自动提取术语库。
7. 用户可以手动修改术语库。
8. 系统可以调用 LLM 翻译 LaTeX 正文。
9. 系统可以生成中文 LaTeX 项目。
10. 系统可以自动编译中文 PDF。
11. 用户可以下载英文 PDF、中文 PDF 和中文 LaTeX 项目。
12. 用户可以在 Web 中并排查看英文 PDF 和中文 PDF。
13. PDF 对照页面支持同步滚动。
14. 翻译失败、编译失败时有明确日志。
15. 刷新页面后任务状态和翻译进度不会丢失。
```

---

## 14. 开发注意事项

### 14.1 不要破坏 LaTeX 结构

这是最高优先级要求。

任何翻译前后都必须保证：

```text
LaTeX 命令尽量不变
引用不变
标签不变
公式不变
图片路径不变
bib 文件不变
```

### 14.2 不要把整篇论文一次性发给 LLM

必须分块处理。

理由：

```text
降低上下文长度压力
方便失败重试
方便进度显示
方便人工检查
方便术语一致性控制
```

### 14.3 不要依赖某一个 LLM 供应商

系统必须只依赖 OpenAI-compatible API。

### 14.4 不要在前端保存 API Key

API Key 只在后端保存和调用。前端显示时脱敏。

### 14.5 不要把 shell 命令暴露给用户

编译命令由系统固定生成。

### 14.6 不要让用户上传文件覆盖系统目录

所有文件操作必须限制在：

```text
workspace/tasks/{task_id}/
```

---

## 15. 推荐初始界面风格

整体风格：

```text
简洁
浅色
科研工具
左侧导航栏
主区域卡片布局
状态明确
日志可展开
```

左侧导航：

```text
任务管理
新建任务
LLM 配置
系统设置
```

任务详情页顶部：

```text
任务名
状态标签
进度条
当前模型
创建时间
操作按钮
```

PDF 对照页：

```text
左：Original English PDF
右：Translated Chinese PDF
顶部：页码、缩放、同步滚动开关、下载按钮
```
