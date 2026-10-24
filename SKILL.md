---
name: expert-meeting-minutes
description: "把券商专家会议、公司高管采访等中文录音整理为严格忠于原文的正式 DOCX 纪要，包含约 1100 字会议汇总与按序编号的 Q&A。使用本地 FunASR 转写，保留审计底稿，并在术语、数字或语音覆盖存在疑问时阻止定稿，等待人工确认。"
---

# 券商专家会议纪要

把一段中文会议录音转成两份产物：正式 DOCX 纪要，以及独立的转写、术语核验和覆盖审计底稿。正式纪要只有“一、会议内容汇总”和“二、Q&A”，不写人名、会议信息、待办、投资结论或附录。

使用提示：发送录音时请同时告知公司/行业，以便建立术语表和判断上下文。

## 核心约束

- 完全依据录音转写。不得增加录音之外的外部事实、背景、比较、评价、投资判断或作者观点；录音中专家自己作出的行业、研发、临床、技术和商业判断必须保留。
- 联网检索只用于确认转写候选、公司名、产品名、专业术语和数字口径；不得用网页内容替专家补充观点。
- 任何待核术语、数字、自我更正或 VAD 语音覆盖缺口未确认前，不得生成正式 DOCX。
- 人名不进入正式纪要。审计底稿只使用匿名说话人编号。
- 删除寒暄、口头禅、重复确认和无意义语气词，但保留实质内容、数据、单位和限定条件。
- 专家判断是正式纪要的核心内容。策略取舍、开发优先级、适应症/靶点选择、患者人群选择、临床终点与路径设计、成功概率、成本判断、竞争判断以及“应做什么、不应做什么”的建议，即使无法用公开资料核实，也必须写入正式纪要，并用中性归因标明其判断属性。

## 工作流

### 1. 检查环境和输入

先运行：

```powershell
& "<skill-dir>/scripts/run_mm.ps1" setup-check --json
```

如果 `funasr` 或 `torch` 缺失，说明将安装免费依赖、模型体积和 D 盘位置，并运行 [安装说明](references/setup.md) 中的脚本。不要自动索取或使用任何付费 API Key。

确认：

- 录音格式为 mp3、m4a、wav 或 mp4。
- 时长不超过 90 分钟。
- 多声道文件必须由用户选择 `--channel mix` 或具体声道，不能假定第一条音轨完整。
- 默认数据目录是 `D:\CodexData\expert-meeting-minutes`；C 盘空间不足时不要改回 C 盘。

### 2. 本地转写

```powershell
& "<skill-dir>/scripts/run_mm.ps1" transcribe "录音.m4a" --out "任务目录" --channel mix
```

如已有确认过的术语表，加 `--glossary "术语表.json"`。脚本会生成本地缓存、`transcript.json` 和 `run-manifest.json`。先检查：

- `coverage.status` 是否为 `pass`。
- 分段是否有空文本、异常跳时或说话人全部为 `SPK?`。
- 是否出现 `[听不清]`、明显同音错字或被截断的句子。

不要因转写“读起来通顺”就认为内容准确，必须回听低置信处。

### 3. 安全规范化

先运行：

```powershell
& "<skill-dir>/scripts/run_mm.ps1" normalize-transcript "任务目录/transcript.json" --out "任务目录"
```

该步骤只自动修正能够唯一确定的写法，包括年份缩写、日期、重复数字和标准缩写，结果写入 `normalization-audit.json`。规则位于 `assets/normalization-rules.json`。

以下内容不得自动确认：

- 同音术语，例如“基械”可能对应“基线”“基因”或“机械”。
- 药名、靶点和机制术语，例如“踏兵”可能对应“他汀”，必须结合用户确认。
- 可能改变事实含义的数字、单位或比较对象。

### 4. 生成人工复核清单

```powershell
& "<skill-dir>/scripts/run_mm.ps1" prepare-review "任务目录/transcript.json" --out "任务目录" --glossary "术语表.json"
```

阅读完整 `transcript.json`，并处理 `review.json` 中的每一项：

1. 回听对应时间段的原录音。
2. 仅在术语或数字存在真实歧义时联网核实，搜索公司官网、交易所公告、公司 IR、权威媒体、论文或标准文档。
3. 在 `source_checks` 中记录 `query`、实际打开的 `url`、支持候选的 `evidence` 和 `retrieved_at`。
4. 把 `status` 改为 `confirmed`。原文正确时，将 `replacement_text` 设为原引文；需要纠正时，填完整修正句。
5. 覆盖缺口没有 `replacement_text`，必须在 `note` 中写清回听结论；无法确认时保持 `open`。

用户可以在对话中直接确认。只有用户明确确认后，助手才能修改复核状态或术语表。应用确认：

```powershell
& "<skill-dir>/scripts/run_mm.ps1" prepare-review "任务目录/transcript.json" --out "任务目录" --glossary "术语表.json" --apply --update-glossary
```

应用后会重新生成复核清单。若全部为 `confirmed`，`review.json` 的 `status` 才会变成 `ready`。

用户也可以直接编辑 `review-proposal.md` 中的“建议”行。确认后直接应用 Markdown 提案，不需要手工同步 JSON：

```powershell
& "<skill-dir>/scripts/run_mm.ps1" apply-proposal "任务目录/transcript.json" --proposal-md "任务目录/review-proposal.md" --out "任务目录"
```

应用后重新运行 `normalize-transcript` 和 `prepare-review`。

### 5. 撰写 minutes.json

阅读完整的已确认转写。按 [数据契约](references/data-contracts.md) 写 `minutes.json`，并按 [写作规范](references/style-guide.md) 成文。不得一边扫读一边摘写。

关键要求：

- 动笔前梳理专家的判断型内容，包括策略、优先级、取舍、适用条件、排除项、路径选择、成功概率和风险看法。不得因为缺少公开数据、无法验证或只是专家个人经验而删掉。
- 汇总为 3 至 5 个连贯自然段，不分点，目标 1000 至 1200 字。
- Q&A 使用 `Q1：问题`，下一段直接写回答，不写 `A：`。
- 按录音中的“实质问题单元”逐条编号。不同问题不得合并；同一事实的连续追问、重复确认和补充数据可以合并为一个 Q，并在一个回答中保留关键数据。
- Q&A 回答直接陈述内容，不得以“专家表示”“专家认为”“专家判断”等前置语开头；判断型内容仍须完整保留，可在答案中用“专家建议”“其判断是”“从开发经验看”等中性措辞标明属性，不得改写成客观事实。
- 每条问答使用一个或多个证据片段 ID；汇总段落也必须有 `summary_segment_ids`。
- 未使用的片段写入 `omissions`，原因只能是 `greeting`、`filler`、`duplicate` 或 `non_substantive`。
- 公司、行业、产品、数据、条件、因果和专家判断保留；提问人、专家姓名去除。
- 不得为了缩短篇幅删去机构名、产品名、机制、研究终点、费用构成、关键对照组或其他实质细节。
- 专家判断与公开资料冲突时，正式纪要保留录音中的判断并标明属性；把核验结果和冲突写入审计底稿，不得用外部结论替换专家发言，也不得把专家判断写成公司确认或客观事实。
- 英文术语保留原文；数据、比例、金额、数量和时间跨度统一使用阿拉伯数字，例如 `2.5亿`、`60%`、`3年`。

### 6. 校验门禁

```powershell
& "<skill-dir>/scripts/run_mm.ps1" validate "任务目录/minutes.json" --transcript "任务目录/transcript.json" --review "任务目录/review.json" --glossary "术语表.json" --out "任务目录/validation.json"
```

必须达到：

- `ok: true`。
- 摘要字数、问答编号、源片段覆盖和数字覆盖全部通过。
- 没有未确认复核项、人名或 `[待核]` 类标记。
- `warnings` 逐条检查。若发现分析性措辞，确认它属于专家原意并带有中性归因，否则改写。

校验失败时修改 `minutes.json` 或复核底稿后重跑。不得手改 `validation.json`。

### 7. 生成并检查 DOCX

```powershell
& "<skill-dir>/scripts/run_mm.ps1" render-docx "任务目录/minutes.json" --validation "任务目录/validation.json" --transcript "任务目录/transcript.json" --review "任务目录/review.json" --out "任务目录/会议纪要.docx"
```

渲染器会拒绝过期校验、未确认复核项、错误输入哈希和已存在文件。生成后用文档渲染能力导出页面图片并逐页检查：

- 标题和两个一级部分完整。
- 中文没有缺字、重叠、截断或异常分页。
- 摘要为自然段，Q&A 标签加粗，回答没有 `A：`。
- 正式 Word 中没有复核标记、来源链接或审计内容。

## 审计目录

每次任务至少保留：

```text
任务目录/
├── 会议纪要.docx
├── transcript.json
├── review.json
├── review.md
├── minutes.json
├── validation.json
├── glossary.json
├── normalization-audit.json
├── proposal-application.json
└── run-manifest.json
```

`transcript.json`、`review.json`、`minutes.json` 和录音都是敏感材料。未经用户明确授权，不上传、不发送、不写入第三方服务。

## 参考文档

- 写作口径、禁止项和 Q&A 示例：[references/style-guide.md](references/style-guide.md)
- JSON 字段和覆盖规则：[references/data-contracts.md](references/data-contracts.md)
- 自动规范化与人工复核边界：[references/normalization-rules.md](references/normalization-rules.md)
- Codex、Claude Code、WorkBuddy 和其他 agent 的安装与质量边界：[references/agent-compatibility.md](references/agent-compatibility.md)
- 免费 FunASR 安装、模型许可和排错：[references/setup.md](references/setup.md)
- 可编辑术语表模板：[assets/glossary-template.json](assets/glossary-template.json)

## 来源与许可

- 转写工具：FunASR，代码采用 MIT 许可。
- 模型：`paraformer-zh`、`fsmn-vad`、`ct-punc`、`cam++`；模型权重受各自模型卡条款约束。
- 项目主页：https://github.com/modelscope/FunASR
- 模型许可：https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE
