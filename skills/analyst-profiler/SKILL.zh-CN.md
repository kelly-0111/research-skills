---
name: analyst-profiler
description: 卖方研究员画像与持续跟踪工作流。适用于结构化卖方研报观点、评估研究员研究质量、区分动量快反型和深度研究型研究员、生成研究员评分卡，并建立持续跟踪数据库。
---

# 卖方研究员画像 Skill

## 目标

这个 skill 用来做基于证据的卖方研究员画像。重点不是主观评价人，而是判断某位研究员的研究对投研工作是否有用。

核心问题：

```text
谁反应快？
谁研究深？
谁的前瞻判断更有效？
谁只在特定行业或行情阶段有优势？
```

## 输入

输入来自研报、晨会纪要、路演笔记、评级调整、目标价调整或人工复盘记录。

最小字段包括：

- 研究员
- 券商
- 行业
- 报告日期
- 标的
- 推荐方向/评级变化
- 观点类型
- 事件滞后天数
- 证据质量、深度、原创性评分
- 报告后股价表现
- 来源标题或文件路径

字段见 `references/schema.md`。

## 工作流

1. 建立 `analyst_call_log.csv`。
2. 标准化研究员、券商、行业、股票、日期和观点字段。
3. 对单篇观点评分：
   - 反应速度
   - 后验表现
   - 证据质量
   - 研究深度和原创性
   - 预测修正纪律
4. 按研究员、行业、观察周期汇总。
5. 给出画像类型：
   - `动量快反型`
   - `深度研究型`
   - `框架驱动型`
   - `均衡型`
   - `跟随型`
   - `样本不足`
6. 输出评分卡、画像摘要和持续跟踪报告。
7. 对样本少、来源缺失、行业不可比的情况写入待补样本。

## 运行评分脚本

如果输入是 Alpha Pai 导出的研究员样本表，先转换字段：

```bash
python3 skills/analyst-profiler/scripts/convert_alpha_pai_dataset.py \
  --input /path/to/analyst_call_log_template.csv \
  --output outputs/analyst_profiler/analyst_call_log_converted.csv
```

再运行评分：

```bash
python3 skills/analyst-profiler/scripts/score_analysts.py \
  --input outputs/analyst_profiler/analyst_call_log_converted.csv \
  --out-dir outputs/analyst_profiler
```

## 质量要求

- 没有来源样本，不给研究员画像。
- 样本少时不能过度下结论。
- 输入行保留来源标题或路径。
- 输出区分 `事实表现`、`推断画像` 和 `待补样本`。
- 画像只作为内部投研 workflow 信号，不作为公开个人评价。
- 尽量在相同行业和相近时间窗口内比较研究员。
