# -*- coding: utf-8 -*-
"""工具② compare_papers —— N 篇论文分层对比(2~5 篇)。

两种模式:
  默认       : 逐篇输出素材 + 两两关键词重叠硬信号,交给 harness 生成对比报告。
  --llm     : 独立模式,脚本自己调 LLM,输出完整对比报告。

用法:
  python compare_papers.py a.pdf b.pdf
  python compare_papers.py a.pdf b.pdf c.pdf --llm
"""
import argparse
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from paper_utils import (  # noqa: E402
    validate_pdf, extract_text, detect_sections, compute_stats,
    load_card, save_card, load_prompt, load_user_profile, clip,
    log_reading, ExtractionError, ensure_utf8_io,
)
from llm import available as llm_available  # noqa: E402

MIN_PAPERS, MAX_PAPERS = 2, 5


def _material_one(path, profile):
    p = validate_pdf(path)
    text = extract_text(p)
    sections = detect_sections(text)
    stats = compute_stats(sections, text)
    sec_map = {s["name"]: s["text"] for s in sections}
    return {
        "tool": "compare_papers",
        "mode": "material",
        "pdf": p,
        "filename": os.path.basename(p),
        "frontmatter": clip(sec_map.get("frontmatter", ""), 1500),
        "sections": {
            k: clip(sec_map.get(k, ""), limits.get(k, 5000))
            for k in limits
        },
        "stats": stats,
        "user_profile": profile or {},
    }


limits = {"abstract": 2500, "introduction": 4000, "method": 5000,
          "experiments": 5000, "related_work": 4000, "conclusion": 2500}


def _tokenize(text):
    return [t for t in re.findall(r"[A-Za-z]{4,}", text.lower())
            if t not in {"that", "with", "this", "these", "from", "have", "which", "their"}]


def _word_overlap(a_text, b_text):
    """两篇论文摘要/引言的关键词 Jaccard 重叠,作为可比性硬信号。"""
    A = set(Counter(_tokenize(a_text)).most_common(40))
    B = set(Counter(_tokenize(b_text)).most_common(40))
    if not A or not B:
        return 0.0
    words_a = {w for w, _ in A}
    words_b = {w for w, _ in B}
    inter = len(words_a & words_b)
    return round(inter / len(words_a | words_b), 3)


def build_materials(paths, profile):
    mats = []
    for p in paths:
        mats.append(_material_one(p, profile))
    # 两两重叠硬信号
    hints = {}
    for i in range(len(mats)):
        for j in range(i + 1, len(mats)):
            a = " ".join([mats[i]["sections"]["abstract"], mats[i]["sections"]["introduction"]])
            b = " ".join([mats[j]["sections"]["abstract"], mats[j]["sections"]["introduction"]])
            hints["%s<->%s" % (i + 1, j + 1)] = _word_overlap(a, b)
    return mats, hints


def format_materials(mats, hints, max_papers):
    out = ["===== 对比素材: %d 篇论文 =====" % len(mats),
           "两两关键词重叠(Jaccard,越高越可能同领域): %s" % hints]
    for i, m in enumerate(mats, 1):
        out.append("")
        out.append("################ PAPER %d/%d: %s ################" % (i, len(mats), m["filename"]))
        if m["frontmatter"]:
            out.append("--- FRONTMATTER ---\n" + m["frontmatter"])
        for name in ["abstract", "introduction", "related_work", "method", "experiments", "conclusion"]:
            body = m["sections"].get(name, "")
            if body:
                out.append("--- %s ---\n%s" % (name.upper(), body))
    return "\n".join(out)


def build_report(paths):
    """--llm 模式:先出卡片再对比。"""
    cards = []
    for p in paths:
        pp = validate_pdf(p)
        c = load_card(pp)
        if not c:
            from parse_paper_core import build_card
            c = build_card(pp)
        cards.append(c)
    from llm import chat
    system = load_prompt("compare.system")
    user = load_prompt("compare.user").replace(
        "{cards}", "\n\n".join("=== 论文%d ===\n%s" % (i + 1, card_json(c))
                               for i, c in enumerate(cards)))
    return chat(system, user)


def card_json(card):
    import json
    return json.dumps(card, ensure_ascii=False, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="工具② N篇论文分层对比(2~5篇)")
    ap.add_argument("pdfs", nargs="+", help="PDF 文件路径(2~5 个)")
    ap.add_argument("--llm", action="store_true", help="独立模式:脚本自己调 LLM 生成对比报告")
    ap.add_argument("--json", action="store_true", help="默认模式下输出素材 JSON")
    args = ap.parse_args(argv)
    ensure_utf8_io()

    if not (MIN_PAPERS <= len(args.pdfs) <= MAX_PAPERS):
        print("错误: 需提供 %d~%d 篇论文,当前 %d 篇" % (MIN_PAPERS, MAX_PAPERS, len(args.pdfs)),
              file=sys.stderr)
        return 2

    try:
        for p in args.pdfs:
            validate_pdf(p)

        if args.llm:
            if not llm_available():
                print("--llm 模式需要 API key(ANTHROPIC_API_KEY 或 OPENAI_API_KEY)。"
                      "无 key 请用默认模式(素材模式)交给 harness 处理。", file=sys.stderr)
                return 1
            report = build_report(args.pdfs)
            log_reading(args.pdfs[0], "ok", {"tool": "compare_papers", "mode": "llm",
                                             "files": [os.path.basename(p) for p in args.pdfs]})
            print(report)
            return 0

        profile = load_user_profile()
        mats, hints = build_materials(args.pdfs, profile)
        log_reading(args.pdfs[0], "ok", {"tool": "compare_papers", "mode": "material",
                                         "files": [os.path.basename(p) for p in args.pdfs]})
        if args.json:
            import json
            print(json.dumps({"materials": mats, "overlap_hints": hints}, ensure_ascii=False, indent=2))
        else:
            print(format_materials(mats, hints, len(args.pdfs)))
        return 0
    except (ValueError, ExtractionError) as e:
        print("错误: %s" % e, file=sys.stderr)
        return 2
    except Exception as e:
        print("未知错误: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
