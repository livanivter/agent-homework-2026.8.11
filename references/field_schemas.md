# Paper Reader 字段定义与输出规范

本文件是三个工具最终输出的**规范(单源真相)**。harness(Claude Code)按此组织回答;
`--llm` 独立模式按 `prompts.md` 的模板 + 本文件的定义产出同样结构。

---

## 工具① parse_paper_core —— 七字段论文卡片

卡片 JSON 结构:

```json
{
  "title": "论文标题",
  "abstract": "摘要要点(2-3句)",
  "problem": "研究问题",
  "motivation": "动机",
  "method": {
    "core_idea": "L0 一句话核心思想(领域无关)",
    "formulation": {"input": "", "output": "", "objective": "", "constraints": ""},
    "framework": [{"component": "组件名", "role": "职责", "flow": "输入→输出"}],
    "details": {
      "model_structure": "模型/系统结构",
      "training": {"loss": "", "optimizer": "", "strategy": ""},
      "data": {"source": "", "preprocess": "", "augmentation": ""},
      "complexity": "计算/内存复杂度"
    },
    "highlights": ["创新点1", "创新点2"],
    "abstract_level": "范式标签"
  },
  "experiments": {"datasets": [], "baselines": [], "metrics": [], "key_results": ""},
  "conclusion": "",
  "limitations": ""
}
```

### 五层方法抽取(L0~L4)

| 层 | 内容 | 说明 |
|---|---|---|
| L0 | core_idea | 领域无关的一句话:用什么思路解决什么问题 |
| L1 | formulation | 问题的形式化:输入/输出/目标/约束 |
| L2 | framework | 组件划分 + 数据流 |
| L3 | details | 领域相关的具体实现:结构/训练/数据/复杂度 |
| L4 | highlights + abstract_level | 作者声称的创新点 + 范式标签 |

### abstract_level 范式标签取值

`end_to_end_learning`(端到端学习) | `symbolic`(符号/规则) |
`search_heuristic`(搜索/启发式) | `system_engineering`(系统工程/优化) |
`theory`(纯理论/证明) | `hybrid`(混合) |

**规则:** 素材缺失的字段填 `""` 或 `[]`,绝不编造;被截断的素材如实标注。

---

## 工具② compare_papers —— 分层对比

### 可比性判定等级

| 等级 | 含义 | 对比方式 |
|---|---|---|
| 强可比 | 同问题 + 同指标 | 逐字段矩阵,可谈结果高低 |
| 部分可比 | 同问题 + 不同方法/指标 | 对齐"问题-方法"维度,指标差异单独标注 |
| 跨领域 | 问题不同(大偏差) | 范式映射表,不硬比结果 |

判定依据:标题/关键词重叠(脚本输出的 Jaccard 硬信号)+ 范式标签 + 方法逻辑。

### 对比报告结构(markdown)

```
## 可比性判定表(两两)
## [同领域] 逐字段对比矩阵 + 差异/共同点/⚠冲突检测
## [跨领域] 范式映射表(问题类型/范式/证据/贡献/成熟度)
## 关系图谱(竞争/启发/互补/无关)
## 横向迁移启示(跨领域方法论借鉴点)
## ⚠ 冲突与不可比声明(承认不可比 = 成功输出)
```

---

## 工具③ analyze_narrative —— 8 维度叙事地图

| # | 维度 | 含义 |
|---|---|---|
| 1 | hook_strategy | 开篇钩子:痛点焦虑/研究空白/数据指标/趋势大势 |
| 2 | gap_framing | 研究空白怎么被文献"围"出来 |
| 3 | positioning | 跟前人区别:first宣称/强主张/增量/跨界迁移 |
| 4 | evidence_arc | 实验编排:先弱后强/消融逐步证明/对比压倒 |
| 5 | rhetoric | 话术特征(结合声称词/模糊词词频) |
| 6 | limitation | 局限写法:主动交代/轻描淡写/回避 |
| 7 | target_reader | 写给谁看 |
| 8 | overall_plot | 一句话故事线 |

**overclaim 检测:** 比对"摘要声称"与"正文证据"是否匹配,判断过度声称;无法判断时如实说明。

**硬统计字段:** 各 section 篇幅占比、引用密度、we 词密度、声称词/模糊词词频。
