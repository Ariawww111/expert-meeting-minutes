# expert-meeting-minutes

一个用于中文专家会议录音整理的 Codex skill：先在本地完成语音转写、术语复核和覆盖审计，再生成包含“会议内容汇总”和编号 Q&A 的正式 DOCX 纪要。

> 使用提示：发送录音时请同时告知公司/行业。

## 功能

- 使用 FunASR 在本机完成中文长音频转写，不依赖付费 API。
- 对术语、数字、自我更正和 VAD 覆盖缺口设置人工复核门禁。
- 保留专家判断、策略取舍、适应症与靶点选择、临床设计、成功概率和竞争判断。
- 生成 3 至 5 段、约 1000 至 1200 字的会议内容汇总与按序编号 Q&A。
- 同时保留 `transcript.json`、`review.json`、`minutes.json`、`validation.json` 等审计底稿。
- 正式 Word 不写专家姓名、来源链接、复核标记、投资结论或附录。

## 环境

- Windows PowerShell
- Python 3.12
- 可用的本地 D 盘数据目录，默认 `D:\CodexData\expert-meeting-minutes`
- 首次安装会下载免费 FunASR 模型，需要网络连接

## 安装

将本仓库放到 Codex skills 目录：

```powershell
git clone https://github.com/Ariawww111/expert-meeting-minutes.git "$HOME\.codex\skills\expert-meeting-minutes"
```

然后安装本地依赖：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$HOME\.codex\skills\expert-meeting-minutes\scripts\setup_env.ps1"
```

安装脚本会创建隔离的 Python 环境、安装 CPU 版 PyTorch 与 FunASR，并把模型缓存写入 `D:\CodexData\expert-meeting-minutes`。

## 使用

在 Codex 中调用：

```text
使用 $expert-meeting-minutes 处理我提供的会议录音。公司/行业是：____。
```

发送录音时请同时提供公司或行业名称。该信息用于建立术语表和判断上下文，不会替代录音内容。

首次使用前可检查环境：

```powershell
& "$HOME\.codex\skills\expert-meeting-minutes\scripts\run_mm.ps1" setup-check --json
```

## 工作流

1. 检查本地模型、磁盘和音频参数。
2. 本地转写并检查 VAD 覆盖率。
3. 规范化确定的日期、缩写和重复数字。
4. 人工复核术语、数字、自我更正和覆盖缺口。
5. 撰写汇总与 Q&A，并保留专家判断。
6. 运行数字、片段覆盖、人名和复核门禁。
7. 生成 DOCX 并逐页检查排版。

详细说明见 [SKILL.md](SKILL.md)，写作口径见 [references/style-guide.md](references/style-guide.md)。

## 隐私

- 录音、转写和纪要默认只保存在本机。
- skill 不要求或使用付费 API Key。
- 首次安装会从公开模型仓库下载模型权重。
- 不要把录音、转写、客户材料或未脱敏纪要提交到本仓库。

## 限制

- 单次录音不超过 90 分钟。
- 多声道录音必须明确选择 `mix` 或具体声道。
- FunASR 可能出现同音词、专有名词和数字错误，必须经过人工复核。
- 正式 DOCX 在术语、数字和覆盖率未确认时会被拒绝生成。

## 上游来源

- FunASR: https://github.com/modelscope/FunASR
- 模型权重及使用条款以对应模型卡和 Model License 为准。
