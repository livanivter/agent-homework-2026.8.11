# -*- coding: utf-8 -*-
"""工具① parse_paper_core —— 解析论文核心内容。

两种模式:
  默认       : 确定性预处理,输出"论文素材"(section 文本 + 硬统计),
              交给 harness(Claude Code)按 references/field_schemas.md 生成卡片。
  --llm     : 独立模式,脚本自己调 LLM(需 ANTHROPIC/OPENAI API key)直接产出七字段卡片。
  --json    : 默认模式下输出结构化 JSON 素材,而非可读文本。

用法:
  python parse_paper_core.py paper.pdf
  python parse_paper_core.py paper.pdf --json
  python parse_paper_core.py paper.pdf --llm [--json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from paper_utils import (  # noqa: E402
    validate_pdf, extract_text, detect_sections, compute_stats,
    load_card, save_card, load_prompt, load_user_profile, clip,
    log_reading, ExtractionError, ensure_utf8_io,
)
from llm import available as llm_available  # noqa: E402


SECTION_LIMIT = 5000       # 每个 section 最多携带字符数
FRONTMATTER_LIMIT = 1500


def build_material(path, user_profile=None):
    """确定性预处理:提取文本 + 定位 section + 统计,并裁剪到可携带长度。"""
    p = validate_pdf(path)
    text = extract_text(p)
    sections = detect_sections(text)
    stats = compute_stats(sections, text)
    sec_map = {s["name"]: s["text"] for s in sections}

    limits = {"abstract": 2500, "introduction": 4000, "method": SECTION_LIMIT,
              "experiments": SECTION_LIMIT, "related_work": 4000,
              "conclusion": 2500}
    material = {
        "tool": "parse_paper_core",
        "mode": "material",
        "pdf": p,
        "filename": os.path.basename(p),
        "frontmatter": clip(sec_map.get("frontmatter", ""), FRONTMATTER_LIMIT),
        "sections": {
            k: clip(sec_map.get(k, ""), limits.get(k, SECTION_LIMIT))
            for k in limits
        },
        "stats": stats,
        "user_profile": user_profile or {},
    }
    return material


def format_material(m):
    """把素材渲染成可读文本,方便 Claude / 人直接读。"""
    out = ["===== PAPER MATERIAL: %s =====" % m["filename"]]
    if m["frontmatter"]:
        out.append("--- FRONTMATTER (标题区) ---")
        out.append(m["frontmatter"])
    for name in ["abstract", "introduction", "related_work", "method", "experiments", "conclusion"]:
        body = m["sections"].get(name, "")
        if not body:
            continue
        out.append("--- %s ---" % name.upper())
        out.append(body)
    out.append("--- 硬统计 ---")
    st = m["stats"]
    out.append("总长度=%d 字符; 引用数=%d; 声称词=%d; 模糊词=%d" % (
        st["total_length"], st["total_citations"], st["total_claims"], st["total_hedges"]))
    sec_ratios = ", ".join("%s=%.0f%%" % (k, v["ratio"] * 100)
                           for k, v in sorted(st["sections"].items(), key=lambda x: x[1]["ratio"], reverse=True)[:5])
    out.append("篇幅占比: " + sec_ratios)
    return "\n".join(out)


def build_card(path):
    """--llm 模式:调 LLM 生成七字段卡片(含五层方法),并缓存。"""
    p = validate_pdf(path)
    cached = load_card(p)
    if cached:
        return cached
    material = format_material(build_material(p))
    from llm import chat, parse_json
    system = load_prompt("parse.system")
    user = load_prompt("parse.user").replace("{material}", material)
    card = parse_json(chat(system, user))
    card["_pdf"] = p
    save_card(p, card)
    return card


def format_card_markdown(card):
    m = card.get("method", {})
    ex = card.get("experiments", {})
    lines = [
        "# 论文卡片: %s" % card.get("title", "(未识别)"),
        "",
        "**问题:** %s" % card.get("problem", "-"),
        "**动机:** %s" % card.get("motivation", "-"),
        "",
        "## 方法(五层)",
        "- L0 核心思想: %s" % m.get("core_idea", "-"),
        "- L1 形式化: %s" % json.dumps(m.get("formulation", {}), ensure_ascii=False),
        "- L2 框架: %s" % json.dumps(m.get("framework", []), ensure_ascii=False),
        "- L3 细节: %s" % json.dumps(m.get("details", {}), ensure_ascii=False),
        "- L4 卖点: %s | 范式: %s" % (m.get("highlights", []), m.get("abstract_level", "-")),
        "",
        "## 实验",
        "- 数据集: %s" % ex.get("datasets", []),
        "- 基线: %s" % ex.get("baselines", []),
        "- 指标: %s" % ex.get("metrics", []),
        "- 关键结果: %s" % ex.get("key_results", "-"),
        "",
        "**结论:** %s" % card.get("conclusion", "-"),
        "**局限:** %s" % card.get("limitations", "-"),
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="工具① 解析论文核心内容")
    ap.add_argument("pdf", help="PDF 文件路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非可读文本")
    ap.add_argument("--llm", action="store_true", help="独立模式:脚本自己调 LLM 生成卡片")
    args = ap.parse_args(argv)
    ensure_utf8_io()

    try:
        if args.llm:
            if not llm_available():
                print("--llm 模式需要 API key(ANTHROPIC_API_KEY 或 OPENAI_API_KEY)。"
                      "无 key 请用默认模式(素材模式)交给 harness 处理。", file=sys.stderr)
                return 1
            card = build_card(args.pdf)
            log_reading(args.pdf, "ok", {"tool": "parse_paper_core", "mode": "llm",
                                         "title": card.get("title")})
            print(json.dumps(card, ensure_ascii=False, indent=2) if args.json
                  else format_card_markdown(card))
            return 0

        # 默认:素材模式
        material = build_material(args.pdf, load_user_profile())
        log_reading(args.pdf, "ok", {"tool": "parse_paper_core", "mode": "material"})
        if args.json:
            print(json.dumps(material, ensure_ascii=False, indent=2))
        else:
            print(format_material(material))
        return 0
    except (ValueError, ExtractionError) as e:
        log_reading(args.pdf, "fail", {"tool": "parse_paper_core", "error": str(e)})
        print("错误: %s" % e, file=sys.stderr)
        return 2
    except Exception as e:
        log_reading(args.pdf, "fail", {"tool": "parse_paper_core", "error": str(e)[:200]})
        print("未知错误: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
