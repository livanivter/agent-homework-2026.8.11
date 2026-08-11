# -*- coding: utf-8 -*-
"""Paper Reader 共用底层:文本提取 / section 定位 / 硬统计 / 缓存 / 阅读记录。

三个工具的公共地基,全部为确定性预处理,不强制依赖 LLM API。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime


def ensure_utf8_io():
    """强制 stdout/stderr 以 UTF-8 输出。

    Windows 上 stdout 被重定向时 Python 默认用 locale 编码(GBK),
    会导致 Claude/下游读取时中文乱码。每个脚本 main 开头调用一次。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class ExtractionError(Exception):
    """文本提取失败(扫描版 / 加密 / 无工具)。"""


def skill_root():
    """返回 skill 根目录(scripts/lib 的上三层)。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def memory_dir():
    d = os.path.join(skill_root(), "memory")
    os.makedirs(d, exist_ok=True)
    return d


def cache_dir():
    d = os.path.join(skill_root(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- 文件校验

MAX_PDF_MB = 50


def validate_pdf(path):
    """校验输入文件,合法返回绝对路径,否则抛 ValueError。"""
    if not path or not os.path.exists(path):
        raise ValueError("文件不存在: %s" % path)
    if os.path.isdir(path):
        raise ValueError("这是一个目录,不是 PDF: %s" % path)
    if os.path.getsize(path) == 0:
        raise ValueError("文件为空: %s" % path)
    if os.path.getsize(path) > MAX_PDF_MB * 1024 * 1024:
        raise ValueError("文件超过 %dMB,超出处理上限: %s" % (MAX_PDF_MB, path))
    if not path.lower().endswith(".pdf"):
        raise ValueError("仅支持 PDF 文件: %s" % path)
    return os.path.abspath(path)


# ---------------------------------------------------------------- 文本提取

def extract_text(path):
    """逐级回退提取 PDF 文本:pymupdf → pypdf → pdftotext CLI。

    全部失败时抛 ExtractionError(说明是扫描版/加密/缺工具)。
    """
    # 1) pymupdf(fitz)
    try:
        import fitz  # type: ignore
    except ImportError:
        fitz = None
    if fitz is not None:
        try:
            doc = fitz.open(path)
            if doc.is_encrypted:
                raise ExtractionError("PDF 已加密,无法提取文本: %s" % path)
            text = "\n".join(page.get_text() for page in doc)
            if text and text.strip():
                return text
        except ExtractionError:
            raise
        except Exception:
            pass

    # 2) pypdf
    try:
        import pypdf  # type: ignore
    except ImportError:
        pypdf = None
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(path)
            if reader.is_encrypted:
                raise ExtractionError("PDF 已加密,无法提取文本: %s" % path)
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(pages)
            if text.strip():
                return text
        except ExtractionError:
            raise
        except Exception:
            pass

    # 3) pdftotext CLI:先 raw 模式(两栏论文正文更连贯),空输出再回退 -layout
    exe = shutil.which("pdftotext")
    if exe:
        for extra in ([], ["-layout"]):
            try:
                res = subprocess.run(
                    [exe] + extra + ["-enc", "UTF-8", str(path), "-"],
                    capture_output=True, timeout=180,
                )
                if res.returncode == 0 and res.stdout and res.stdout.strip():
                    return res.stdout.decode("utf-8", errors="replace")
            except Exception:
                pass

    raise ExtractionError(
        "无法提取文本:文件可能是扫描版(纯图片)或加密 PDF,且未安装 pymupdf/pypdf 解析库。"
    )


# ---------------------------------------------------------------- section 定位

SECTION_ALIASES = {
    "abstract": ["abstract"],
    "introduction": ["introduction", "introduction and motivation",
                     "introduction and background", "introduction and related work"],
    "related_work": ["related work", "related works", "background", "prior work",
                     "background and related work", "related work and background"],
    "method": ["method", "methodology", "approach", "model", "our approach",
               "proposed method", "proposed approach", "system design", "framework",
               "methods", "method and model", "proposed system"],
    "experiments": ["experiments", "experimental setup", "experimental results",
                    "evaluation", "results", "evaluation and results",
                    "experiments and results", "empirical evaluation",
                    "experimental evaluation", "evaluation results"],
    "conclusion": ["conclusion", "conclusions", "conclusion and future work",
                   "discussion", "summary", "concluding remarks",
                   "discussion and conclusion", "conclusion and discussion"],
    "references": ["references", "bibliography", "works cited"],
}

# 两栏版式里,同一物理行可能混排左右两栏(pdftotext -layout 时),
# 用 ≥3 个连续空格把一行切成"栏块",再逐块判标题。
_GAP_RE = re.compile(r"[ \t]{3,}")


def _match_heading(text):
    """text 若是一个 section 标题,返回节名,否则 None。"""
    s = (text or "").strip().rstrip(".:")
    if not s or len(s) > 60:
        return None
    core = re.sub(r"^\d+(?:\.\d+)*[\.\)\-]?\s+", "", s).strip().lower()
    for name, aliases in SECTION_ALIASES.items():
        if core in aliases:
            return name
    return None


def detect_sections(text):
    """扫描文本,返回有序的 [{'name': section名, 'start': 起始行号, 'text': 该节文本}]。

    'frontmatter' 表示标题页/摘要之前的内容。未匹配到的节名不会出现。
    兼容单栏(整行为标题)与两栏(标题混排在某一行内)两种版式。
    """
    lines = text.splitlines()
    hits = []  # (line_idx, section_name)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # 整行≤90 按整行判;否则拆成栏块逐块判
        chunks = [line] if len(stripped) <= 90 else [c for c in _GAP_RE.split(line) if c.strip()]
        for ch in chunks:
            name = _match_heading(ch)
            if name:
                hits.append((i, name))
                break

    # 去掉重复(同一节名连续命中只取第一次)
    dedup = []
    seen = set()
    for i, name in hits:
        if name not in seen:
            seen.add(name)
            dedup.append((i, name))

    if not dedup:
        return [{"name": "fulltext", "start": 0, "text": text}]

    sections = []
    # frontmatter:正文第一个标题之前的内容
    first_idx = dedup[0][0]
    if first_idx > 0:
        head = "\n".join(lines[:first_idx]).strip()
        if head:
            sections.append({"name": "frontmatter", "start": 0, "text": head})

    for k, (i, name) in enumerate(dedup):
        end = dedup[k + 1][0] if k + 1 < len(dedup) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip()
        if body:
            sections.append({"name": name, "start": i, "text": body})
    return sections


def section_map(sections):
    """返回 {section名: 文本} 的字典,方便按名取用。"""
    return {s["name"]: s["text"] for s in sections}


# ---------------------------------------------------------------- 硬统计

CLAIM_WORDS = [
    "state-of-the-art", "sota", "novel", "first", "unprecedented",
    "outperform", "outperforms", "superior", "best", "achieves", "the best",
]
HEDGE_WORDS = [
    "we believe", "we think", "we hope", "to the best of our knowledge",
    "may", "might", "could potentially", "possibly", "hopefully",
    "in general", "can potentially", "suggests that",
]


def compute_stats(sections, total_text=None):
    """计算叙事剖析用的硬统计特征。"""
    total = total_text or "\n".join(s["text"] for s in sections)
    n_total = max(len(total), 1)
    sec_stats = {}
    for s in sections:
        body = s["text"]
        sec_stats[s["name"]] = {
            "length": len(body),
            "ratio": round(len(body) / n_total, 4),
            "citations": len(re.findall(r"\[[0-9,\-]+\]|\([A-Z][^)]{2,60}\s*,\s*20\d\d\)", body)),
            "we_words": len(re.findall(r"\bwe\b|\bour\b", body, re.IGNORECASE)),
            "claims": sum(len(re.findall(r"\b%s\b" % re.escape(w), body, re.IGNORECASE)) for w in CLAIM_WORDS),
            "hedges": sum(len(re.findall(re.escape(w), body, re.IGNORECASE)) for w in HEDGE_WORDS),
        }
    return {
        "total_length": len(total),
        "sections": sec_stats,
        "total_claims": sum(s["claims"] for s in sec_stats.values()),
        "total_hedges": sum(s["hedges"] for s in sec_stats.values()),
        "total_citations": sum(s["citations"] for s in sec_stats.values()),
    }


# ---------------------------------------------------------------- JSON / 缓存 / 记录

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def file_digest(path):
    """按 路径+大小+修改时间 生成缓存 key。"""
    st = os.stat(path)
    return hashlib.sha1(
        ("%s|%d|%d" % (os.path.abspath(path), st.st_size, int(st.st_mtime))).encode("utf-8")
    ).hexdigest()[:16]


def load_card(path):
    c = os.path.join(cache_dir(), "card_%s.json" % file_digest(path))
    return load_json(c)


def save_card(path, card):
    c = os.path.join(cache_dir(), "card_%s.json" % file_digest(path))
    save_json(c, card)
    return c


def log_reading(file_path, status, extra=None):
    """向 memory/reading_history.json 追加一条处理记录(记忆能力的写路径之一)。"""
    entry = {
        "file": os.path.basename(file_path),
        "status": status,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if extra:
        entry.update(extra)
    history = load_json(os.path.join(memory_dir(), "reading_history.json"), [])
    history.append(entry)
    history = history[-500:]  # 只保留最近 500 条
    save_json(os.path.join(memory_dir(), "reading_history.json"), history)


def load_prompt(name):
    """从 references/prompts.md 读取一段提示词模板(单源真相)。

    模板文件用 `## 名字` 分段;harness 与 --llm 模式共用同一份。
    """
    path = os.path.join(skill_root(), "references", "prompts.md")
    if not os.path.exists(path):
        raise FileNotFoundError("缺少 references/prompts.md")
    text = open(path, encoding="utf-8").read()
    m = re.search(r"^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(name), text, re.M | re.S)
    if not m:
        raise ValueError("prompts.md 中找不到片段: %s" % name)
    return m.group(1).strip()


def clip(text, limit, marker="\n[...已截断,共%d字...]"):
    """截断到 limit 字符,超长加标记。"""
    if len(text) <= limit:
        return text
    return text[:limit] + (marker % len(text))


def load_user_profile():
    """读取用户偏好记忆,不存在则返回默认。"""
    defaults = {
        "user_notes": "",
        "preferred_domains": [],
        "preferred_conferences": [],
        "summary_depth": "full",   # full | brief
        "compare_max_papers": 5,
        "output_language": "auto",
    }
    p = load_json(os.path.join(memory_dir(), "user_profile.json"), {})
    merged = dict(defaults)
    merged.update(p or {})
    return merged
