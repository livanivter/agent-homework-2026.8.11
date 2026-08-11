# -*- coding: utf-8 -*-
"""Paper Reader —— 自包含 ReAct Agent 循环(不依赖 Claude Code)。

Agent = LLM(DeepSeek, OpenAI 兼容 function calling)
      + Tools(三个论文工具 + read_memory + update_profile 共 5 个)
      + Memory(memory/ 下 JSON 文件,以工具形式参与决策)

用法:
  python agent.py "对比 FedMD 和 FedProto,并记住我的偏好"
  python agent.py                # 交互式对话(输入任务,Ctrl+C 退出)
  python agent.py --max-steps 12 "任务"
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import analyze_narrative  # noqa: E402
import compare_papers     # noqa: E402
import parse_paper_core   # noqa: E402
from llm import chat_tools, available  # noqa: E402
from paper_utils import (  # noqa: E402
    load_user_profile, read_memory_summary, update_user_profile,
    ensure_utf8_io, log_reading,
)

SYSTEM_PROMPT = """你是"Paper Reader"学术论文阅读助手 Agent,面向研究生科研场景的学术论文阅读与分析。
你通过工具获取论文素材与记忆,再自己组织最终分析。输出用中文,markdown 格式。

可用工具:
1. parse_paper(file_path) — 解析单篇论文,返回分节素材 + 硬统计。据此产出【七字段论文卡片】:
   title / problem / motivation / method(五层 L0核心思想 L1形式化 L2框架 L3技术细节 L4卖点+范式标签 abstract_level) / experiments / conclusion / limitations
2. compare_papers(file_paths) — 对比 2~5 篇,返回各篇素材 + 两两关键词重叠硬信号。据此产出【分层对比报告】:
   可比性判定表(强可比/部分可比/跨领域) → 同领域逐字段矩阵 或 跨领域范式映射表 → 关系图谱 → 横向迁移启示 → 冲突与不可比声明
3. analyze_narrative(file_path, aspect?) — 返回摘要/引言/结论 + 叙事硬统计。据此产出【8维叙事地图】:
   hook_strategy / gap_framing / positioning / evidence_arc / rhetoric / limitation / target_reader / overall_plot,末尾做 overclaim 检测
4. read_memory() — 读取记忆:用户偏好 + 最近阅读历史。任务开始前先调用。
5. update_profile(notes, preferred_domains) — 任务后如学到新用户偏好,调用它写入记忆。

规则:
- 任务开始前先调用 read_memory() 了解用户偏好,再开始分析。
- 分析必须基于工具返回的素材,禁止编造论文内容;素材缺失/加密/扫描版时如实说明。
- 你可以一次调用多个工具并行获取素材,拿到结果后综合回答。
- 跨领域论文"不可比"是有效结论,不要硬编对比结果。
- 任务完成后如学到新偏好,用 update_profile() 记录。"""

TOOLS = [
    {"type": "function", "function": {
        "name": "parse_paper",
        "description": "解析一篇论文 PDF,返回分节素材与硬统计。用于生成七字段论文卡片。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "论文 PDF 的绝对路径"},
            },
            "required": ["file_path"],
        },
    }},
    {"type": "function", "function": {
        "name": "compare_papers",
        "description": "对比 2~5 篇论文,返回各篇素材与两两关键词重叠硬信号。用于生成分层对比报告。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_paths": {"type": "array", "items": {"type": "string"},
                               "description": "2~5 个 PDF 绝对路径,顺序即编号"},
            },
            "required": ["file_paths"],
        },
    }},
    {"type": "function", "function": {
        "name": "analyze_narrative",
        "description": "剖析论文写作策略,返回摘要/引言/结论与叙事硬统计。用于生成 8 维叙事地图。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "论文 PDF 的绝对路径"},
                "aspect": {"type": "string",
                           "enum": ["hook_strategy", "gap_framing", "positioning",
                                    "evidence_arc", "rhetoric", "limitation",
                                    "target_reader", "overall_plot"],
                           "description": "可选:只剖析某一维度"},
            },
            "required": ["file_path"],
        },
    }},
    {"type": "function", "function": {
        "name": "read_memory",
        "description": "读取记忆:用户偏好与最近阅读历史。任务开始前调用。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "update_profile",
        "description": "把学到的新用户偏好写入记忆(如常用领域、摘要深度、结论偏好)。",
        "parameters": {
            "type": "object",
            "properties": {
                "notes": {"type": "string", "description": "要记住的用户偏好说明"},
                "preferred_domains": {"type": "array", "items": {"type": "string"},
                                      "description": "用户常关注的领域关键词"},
            },
        },
    }},
]


def execute_tool(name, args):
    """执行一个工具,返回字符串结果。"""
    if name == "parse_paper":
        path = args["file_path"]
        m = parse_paper_core.build_material(path, load_user_profile())
        log_reading(path, "ok", {"tool": "agent:parse_paper"})
        return parse_paper_core.format_material(m)
    if name == "compare_papers":
        paths = args["file_paths"]
        mats, hints = compare_papers.build_materials(paths, load_user_profile())
        log_reading(paths[0], "ok", {"tool": "agent:compare_papers",
                                     "files": [os.path.basename(p) for p in paths]})
        return compare_papers.format_materials(mats, hints, len(mats))
    if name == "analyze_narrative":
        path = args["file_path"]
        m = analyze_narrative.build_material(path, load_user_profile(), args.get("aspect"))
        log_reading(path, "ok", {"tool": "agent:analyze_narrative",
                                 "aspect": args.get("aspect")})
        return analyze_narrative.format_material(m)
    if name == "read_memory":
        return json.dumps(read_memory_summary(), ensure_ascii=False, indent=2)
    if name == "update_profile":
        p = update_user_profile(
            notes=args.get("notes"),
            preferred_domains=args.get("preferred_domains"),
        )
        return "已写入记忆: " + json.dumps(p, ensure_ascii=False)
    raise ValueError("未知工具: %s" % name)


def run_agent(task, max_steps=8):
    """ReAct 循环:LLM 决策 → 调工具 → 回填结果 → 再决策,直到无工具调用。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    for step in range(1, max_steps + 1):
        content, tool_calls = chat_tools(messages, TOOLS)
        if not tool_calls:
            return (content or "").strip() or "(空回复)"
        calls = ", ".join("%s(%s)" % (c["name"], json.dumps(c["arguments"], ensure_ascii=False))
                          for c in tool_calls)
        print("  [step %d] agent 决策调用: %s" % (step, calls))
        messages.append({
            "role": "assistant", "content": content or "",
            "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"],
                              "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                for c in tool_calls
            ],
        })
        for c in tool_calls:
            try:
                result = execute_tool(c["name"], c["arguments"])
            except Exception as e:
                result = "工具执行失败: %s" % e
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
    return "达到最大步数(%d),未得到最终答案。" % max_steps


def repl(max_steps):
    print("Paper Reader Agent(DeepSeek)。输入任务,Ctrl+C / 输入 exit 退出。")
    while True:
        try:
            task = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break
        if not task:
            continue
        if task.lower() in ("exit", "quit"):
            break
        try:
            print(run_agent(task, max_steps))
        except KeyboardInterrupt:
            print("\n(中断)")
            break
        except Exception as e:
            print("错误: %s" % e)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Paper Reader ReAct Agent")
    ap.add_argument("task", nargs="?", help="任务(不给则进入交互模式)")
    ap.add_argument("--max-steps", type=int, default=8)
    args = ap.parse_args(argv)
    ensure_utf8_io()

    if not available():
        print("未配置 LLM:请在 .env 中设置 LLM_PROVIDER 与对应 key(如 DEEPSEEK_API_KEY)。",
              file=sys.stderr)
        return 1
    try:
        if args.task:
            print(run_agent(args.task, args.max_steps))
        else:
            repl(args.max_steps)
    except Exception as e:
        print("错误: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
