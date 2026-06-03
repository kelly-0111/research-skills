---
name: innovative-drug-research
description: 创新药投研工作流。适用于结构化创新药公司、管线、靶点、适应症、临床阶段、最新进展和催化剂，也适用于把这些事实连接到医药股上涨逻辑、事件催化、资金轮动、行情阶段和风险信号。
---

# 创新药投研助手

## 目标

这个 skill 是创新药投研的主入口，包含三个子模块：

1. **资料接入**：先收集和分层管理资料来源。
2. **管线结构化**：再建立事实底稿。
3. **上涨逻辑复盘**：最后解释股价和板块行情。

两个模块是上下游关系：

```text
AlphaPai/API资料来源 → source manifest → 管线事实 → 进展/催化剂/BD → 股价上涨逻辑 → 风险信号
```

不要编造药物事实，也不要把未经证实的股价原因写成事实。不确定的信息标注 `待确认` 或 `待核验线索`。

## 如何选择模块

当用户要做这些事时，用 **资料接入**：

- 加入更多真实资料，跟踪靶向创新药发展
- 使用 AlphaPai、Alpha派、PaiPai 或 AlphaPai API 作为公告、研报、路演、点评、社媒、表格、图片的数据入口
- 收集公司官网投资者关系和新闻/媒体页面，例如财务报告、公告与通函、演示材料、IR月报/周报、日历、产品管线页、全球合作页、新闻中心、公司新闻列表和媒体报道
- 判断现在是否需要 API，还是先用本地资料池
- 标准化公告、官网管线页、年报、临床登记、会议摘要、研报
- 建立或更新 source manifest

读取：

- `references/source_intake.md`
- `references/alphapai_adapter.md`
- `references/schemas.md`

当用户要做这些事时，用 **管线结构化**：

- 梳理所有创新药靶点和进展
- 建公司/药物/靶点/适应症/临床阶段数据库
- 从公司列表、研报、PPT、公告、AlphaPai 输出中提取结构化字段
- 输出公司池、管线进展表、催化剂表、待确认清单

读取：

- `references/general_pipeline_workflow.md`
- `references/pipeline_structuring.md`
- `references/schemas.md`

当任务涉及通用 Excel 底表、AlphaPai 数据召回、数据质量审查、防止不同项目字段串线、或判断有/无 baseline 的公司如何处理时，以 `references/general_pipeline_workflow.md` 作为主流程。

当用户要做这些事时，用 **上涨逻辑复盘**：

- 分析医药股为什么涨
- 复盘创新药行情、事件催化、BD交易、会议前后交易
- 区分基本面、叙事、流动性、资金轮动、情绪扩散
- 判断行情阶段、利好兑现和见顶风险

读取：

- `references/rally_logic.md`

当用户要从“创新药资料”一路分析到“股价逻辑”时，两个模块串联：

1. 先把资料登记到 source manifest。
2. 再结构化公司、药物、靶点、阶段、进展和催化剂。
3. 再用这些事实解释行情和个股上涨逻辑。
4. 输出时区分 `已确认事实`、`推断` 和 `待核验线索`。

## 默认产出

管线结构化产出：

- `company_ir_sources.csv`
- `source_manifest.csv`
- `company_master.csv`
- `pipeline_progress.csv`
- `catalyst_tracker.csv`
- `bd_deal_tracker.csv`
- `verification_queue.csv`

上涨逻辑复盘产出：

- 行情复盘报告
- 催化剂地图
- 代表公司分组表
- 风险/见顶信号清单
- 待核验事项

## 运行种子表脚本

当输入是 Markdown 公司列表时，运行：

```bash
python3 skills/innovative-drug-research/scripts/build_pipeline_seed.py \
  --company-list /path/to/company_list.md \
  --out-dir outputs/innovative_drug_research
```

脚本会生成第一版公司主表、代表性管线种子表、催化剂种子表和待确认清单。

脚本里的 `PIPELINE_SEEDS` 只是 starter examples，用来生成第一版映射和待验证入口，不是完整创新药管线库，也不是最终投研结论。

当 AlphaPai API 可用时，用 `alphapai-research` 负责数据召回，用本 skill 负责来源登记、结构化、核验、追踪表和最终交付物。API Key 只配置在本机 AlphaPai skill 或本地环境中，不写入本仓库。

## 质量要求

- 宁可写 `待确认`，不要猜。
- 每行保留来源文件。
- 保留来源可信度和核验状态。
- 区分事件时间和维护时间：来源发布日期、检索日期、进展日期、催化剂时间窗口、BD公告/签约/生效日期、最近核验日期、表格更新时间不要混在一个字段里。
- 不把行情复盘材料里的观点直接当成临床事实。
- 同一药物多适应症、同一公司多管线时，信息足够则拆行。
- 有 BD 交易信息时单独记录合作方、授权区域、首付款、里程碑、股权/期权条款、覆盖资产和来源可信度。
- 生成 Excel 时按 `general_pipeline_workflow.md` 控制结构：前两行合并为标题/来源，单公司不重复生成公司明细 tab，`汇总` 为项目级摘要，`靶点-适应症明细` 按公司→靶点→药物/项目→适应症排序分组，BD tab 使用紧凑核心列，主表进展/事件写提炼摘要，完整来源和原始摘录放 `附件索引`。
- 股价原因没有来源时，标注为 `待核验线索`。
- 输出要方便持续更新，而不是一次性总结。
