# Paper Reader —— 学术论文阅读助手

垂直领域 Agent 产品:面向研究生科研场景的论文阅读与分析。
**Agent = LLM(Claude Code harness) + Tools(3 个脚本) + Memory(JSON 文件)。**
打包为 **Claude Code Skill**,呼应《Agent 专题》课程的 Skills/MCP 专题。

分析链:`写了什么(事实) → 和别人比有什么不同(关系) → 为什么要这么写(意图)`。

## 目录结构

```
paper-reader-skill/
├── SKILL.md                   # 技能定义:触发条件 / 工具调用 / 工作流 / 记忆维护
├── scripts/
│   ├── parse_paper_core.py    # 工具① 解析核心内容(七字段卡片 + 五层方法抽取)
│   ├── compare_papers.py      # 工具② N篇分层对比(2~5篇,同领域/跨领域)
│   ├── analyze_narrative.py   # 工具③ 叙事剖析(8维度 + overclaim检测)
│   └── lib/
│       ├── paper_utils.py     # 共用底层:文本提取/section定位/硬统计/缓存/记忆
│       └── llm.py             # 可选 LLM 客户端(urllib,零依赖)
├── references/
│   ├── field_schemas.md       # 字段定义与输出规范(单源真相)
│   └── prompts.md             # 提示词模板(--llm 模式与 harness 共用)
└── memory/
    ├── user_profile.json      # 用户偏好(Claude 维护)
    └── reading_history.json   # 阅读记录(脚本自动追加,gitignore)
```

## 环境要求

- Python 3.9+,无第三方依赖
- PDF 文本提取:pdftotext CLI(有 pymupdf/pypdf 时优先)
- 默认素材模式**无需 API key**;`--llm` 独立模式需 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`

## 用法

三个脚本都支持两种模式:

| 模式 | 说明 |
|---|---|
| 默认(素材模式) | 脚本做确定性预处理,输出分节文本 + 硬统计,交 Claude Code 推理 |
| `--llm` | 脚本自己调 LLM,直接产出最终结果(需 API key) |

```bash
# 工具① 解析单篇
python scripts/parse_paper_core.py paper.pdf
python scripts/parse_paper_core.py paper.pdf --json
python scripts/parse_paper_core.py paper.pdf --llm

# 工具② 对比 2~5 篇(顺序即编号)
python scripts/compare_papers.py a.pdf b.pdf
python scripts/compare_papers.py a.pdf b.pdf c.pdf d.pdf --llm

# 工具③ 叙事剖析(可选 --aspect 单维度)
python scripts/analyze_narrative.py paper.pdf
python scripts/analyze_narrative.py paper.pdf --aspect hook_strategy
```

作为 Skill 使用时,Claude Code 会根据用户意图自动选择并调用上述工具。

## 记忆能力

- `user_profile.json` —— 用户偏好(领域/会议/摘要深度/对比上限),任务前读、任务后更新
- `reading_history.json` —— 每篇处理记录,脚本自动追加

## 三工具设计

1. **parse_paper_core**:七字段卡片,方法部分五层抽取(L0 核心思想 → L4 卖点与范式),输出 `abstract_level` 范式标签
2. **compare_papers**:可比性判定(强可比/部分可比/跨领域)→ 同领域逐字段矩阵 / 跨领域范式映射表 → 关系图谱 → 横向迁移启示 → 不可比声明
3. **analyze_narrative**:8 维度叙事地图 + 硬统计 + overclaim 检测(摘要声称 vs 正文证据)

详细字段定义见 `references/field_schemas.md`。

## 已知限制(边界行为)

- 两栏/扫描版 PDF 的 section 边界可能有少量串栏;标题检测为启发式
- 参考文献有时与结论相邻,依赖 References 标题正确分节
- 跨领域论文"不可比"时如实声明,不强编结果
