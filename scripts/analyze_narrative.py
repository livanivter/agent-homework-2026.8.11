# -*- coding: utf-8 -*-
"""工具③ analyze_narrative —— 论文叙事剖析(为什么这么写)。

两种模式:
  默认       : 确定性预处理,输出 section 文本 + 叙事硬统计,交给 harness 生成 8 维叙事地图。
  --llm     : 独立模式,脚本自己调 LLM,直接输出叙事地图(含 overclaim 检测)。

用法:
  python analyze_narrative.py paper.pdf
  python analyze_narrative.py paper.pdf --aspect hook_strategy
  python analyze_narrative.py paper.pdf --llm
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from paper_utils import (  # noqa: E402
    validate_pdf, extract_text, detect_sections, compute_stats,
    load_prompt, load_user_profile, clip, log_reading, ExtractionError,
    ensure_utf8_io,
)
from llm import available as llm_available  # noqa: E402

ASPECTS = ["hook_strategy", "gap_framing", "positioning", "evidence_arc",
           "rhetoric", "limitation", "target_reader", "overall_plot"]


def build_material(path, profile=None, aspect=None):
    p = validate_pdf(path)
    text = extract_text(p)
    sections = detect_sections(text)
    stats = compute_stats(sections, text)
    sec_map = {s["name"]: s["text"] for s in sections}
    return {
        "tool": "analyze_narrative",
        "mode": "material",
        "pdf": p,
        "filename": os.path.basename(p),
        "aspect": aspect,
        "abstract": clip(sec_map.get("abstract", ""), 3000),
        "introduction": clip(sec_map.get("introduction", ""), 5000),
        "conclusion": clip(sec_map.get("conclusion", ""), 3000),
        "stats": stats,
        "user_profile": profile or {},
    }


def format_material(m):
    out = ["===== 叙事剖析素材: %s =====" % m["filename"]]
    if m["aspect"]:
        out.append("指定剖析维度: %s" % m["aspect"])
    out.append("--- ABSTRACT ---\n" + m["abstract"])
    out.append("--- INTRODUCTION ---\n" + m["introduction"])
    out.append("--- CONCLUSION ---\n" + m["conclusion"])
    out.append("--- 叙事硬统计 ---")
    st = m["stats"]
    out.append("总长度=%d; 引用=%d; 声称词=%d; 模糊词=%d" % (
        st["total_length"], st["total_citations"], st["total_claims"], st["total_hedges"]))
    for name, s in st["sections"].items():
        out.append("  [%s] 篇幅=%.0f%% 引用=%d we词=%d 声称=%d 模糊=%d" % (
            name, s["ratio"] * 100, s["citations"], s["we_words"], s["claims"], s["hedges"]))
    return "\n".join(out)


def build_narrative(path, aspect=None):
    """--llm 模式:调 LLM 生成 8 维叙事地图。"""
    from llm import chat
    material = format_material(build_material(path, aspect=aspect))
    system = load_prompt("narrative.system")
    user = load_prompt("narrative.user").replace("{material}", material)
    if aspect:
        user += "\n\n本次只剖析维度: %s" % aspect
    return chat(system, user)


def main(argv=None):
    ap = argparse.ArgumentParser(description="工具③ 论文叙事剖析")
    ap.add_argument("pdf", help="PDF 文件路径")
    ap.add_argument("--aspect", choices=ASPECTS, help="只剖析某一维度")
    ap.add_argument("--llm", action="store_true", help="独立模式:脚本自己调 LLM 输出叙事地图")
    ap.add_argument("--json", action="store_true", help="默认模式下输出素材 JSON")
    args = ap.parse_args(argv)
    ensure_utf8_io()

    try:
        if args.llm:
            if not llm_available():
                print("--llm 模式需要 API key(ANTHROPIC_API_KEY 或 OPENAI_API_KEY)。"
                      "无 key 请用默认模式(素材模式)交给 harness 处理。", file=sys.stderr)
                return 1
            report = build_narrative(args.pdf, args.aspect)
            log_reading(args.pdf, "ok", {"tool": "analyze_narrative", "mode": "llm",
                                         "aspect": args.aspect})
            print(report)
            return 0

        material = build_material(args.pdf, load_user_profile(), args.aspect)
        log_reading(args.pdf, "ok", {"tool": "analyze_narrative", "mode": "material",
                                     "aspect": args.aspect})
        if args.json:
            import json
            print(json.dumps(material, ensure_ascii=False, indent=2))
        else:
            print(format_material(material))
        return 0
    except (ValueError, ExtractionError) as e:
        log_reading(args.pdf, "fail", {"tool": "analyze_narrative", "error": str(e)})
        print("错误: %s" % e, file=sys.stderr)
        return 2
    except Exception as e:
        print("未知错误: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
