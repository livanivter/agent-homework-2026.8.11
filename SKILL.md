---
name: paper-reader
description: 学术论文阅读助手。当用户请求解析论文核心内容("看看这篇讲了啥"/"总结这篇的方法/实验")、对比多篇论文("对比这几篇"/"谁更好"/"它们什么关系")、或剖析论文写作策略("这篇为什么这么写"/"怎么讲故事的"/"有没有过度声称")时使用。基于三个确定性预处理工具 + JSON 记忆,产出结构化分析。
---

# Paper Reader(学术论文阅读助手)

垂直领域 Agent 产品:面向研究生科研场景的论文阅读与分析。Agent = LLM(本 harness)+ Tools(3 个脚本)+ Memory(memory/ 下两个 JSON)。

## 工作目录

所有命令在 skill 根目录运行(`cd` 到 `paper-reader-skill`)。

## 前提

- Python 3.9+,无第三方依赖;PDF 文本提取走 pdftotext CLI(pymupdf/pypdf 存在时优先)。
- 默认**素材模式**不需要 API key。
- 若用户配置了 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`,可加 `--llm` 让脚本独立产出最终结果;无 key 时走素材模式,由本 harness 完成推理。
- 另有自包含 ReAct Agent(`scripts/agent.py`),走 DeepSeek function calling,不依赖本 harness;用户提到"用 agent / 自动跑 / 循环"时指引其使用。

## 记忆(读写时机)

- **任务前:** 读 `memory/user_profile.json`(用户偏好:领域/会议/摘要深度/对比上限)与 `memory/reading_history.json`(读史)。
- **任务后:** 若学到新偏好(如用户新说了常用领域、摘要深度偏好),更新 `user_profile.json`;脚本会自动把处理记录追加进 `reading_history.json`。

## 工具调用

### 工具① parse_paper_core —— 解析核心内容

**用户意图:** 解析单篇论文的问题/方法/实验/结论。

```bash
python scripts/parse_paper_core.py "<pdf路径>"
```

输出分节素材(FRONTMATTER/ABSTRACT/INTRO/RELATED WORK/METHOD/EXPERIMENTS/CONCLUSION + 硬统计)。按 `references/field_schemas.md` 的**七字段卡片 + 五层方法(L0-L4)** 组织最终卡片(markdown)。方法部分务必给出 L0 一句话核心思想、L4 范式标签与创新点。

### 工具② compare_papers —— 对比 2~5 篇

**用户意图:** 对比多篇、谁更强、什么关系、跨领域论文。

```bash
python scripts/compare_papers.py "<a.pdf>" "<b.pdf>" ["<c.pdf>" ...]
```

输出各篇素材 + **两两关键词重叠 Jaccard 硬信号**。按 `references/field_schemas.md` 的**分层对比**原则产出报告:可比性判定表 → 同领域逐字段矩阵 / 跨领域范式映射表 → 关系图谱 → 横向迁移启示 → 冲突与不可比声明。**承认不可比也是有效输出**,不要硬比跨领域结果。

### 工具③ analyze_narrative —— 叙事剖析

**用户意图:** 论文为什么这么写、写作策略、过度声称。

```bash
python scripts/analyze_narrative.py "<pdf路径>" [--aspect hook_strategy|gap_framing|positioning|evidence_arc|rhetoric|limitation|target_reader|overall_plot]
```

输出摘要/引言/结论 + **叙事硬统计**(篇幅占比/引用密度/we 词/声称词/模糊词)。按 `references/field_schemas.md` 的 **8 维度叙事地图**产出剖析,末尾做 **overclaim 检测**(摘要声称 vs 正文证据)。

## 工作流

1. 读记忆(`user_profile.json` + `reading_history.json`),确认偏好(摘要深度/语言/领域)。
2. 判断用户意图 → 选工具 → 运行脚本(注意 Windows 路径用引号包裹)。
3. 读脚本输出素材,按 `references/field_schemas.md` 的 schema 组织最终回答。
4. 任务后更新 `user_profile.json`(只追加新偏好,不覆盖已有字段)。
5. 脚本报错(加密/扫描版/路径错误)时**如实转达错误信息,不编造论文内容**。
