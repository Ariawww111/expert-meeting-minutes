# Agent 兼容性

本 skill 的转写、复核、校验和 DOCX 渲染由本地 Python 脚本完成。Codex、Claude Code 和腾讯 WorkBuddy/CodeBuddy 共用同一套 `SKILL.md` 与脚本，因此确定性环节和门禁一致；汇总与 Q&A 的语言风格取决于各 agent 使用的模型。

## 安装位置

| Agent | 用户级目录 |
| --- | --- |
| Codex | `%USERPROFILE%\.codex\skills\expert-meeting-minutes` |
| Claude Code | `%USERPROFILE%\.claude\skills\expert-meeting-minutes` |
| WorkBuddy/CodeBuddy | `%USERPROFILE%\.codebuddy\skills\expert-meeting-minutes` |

可在克隆后的仓库运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_skill.ps1 -Target All
```

默认使用复制模式，避免各客户端对目录链接支持不一致。更新仓库后重新运行安装脚本并加 `-Force`。

## 不同 Agent 的边界

- **Codex**：直接执行本地脚本并使用完整 skill 工作流。
- **Claude Code**：从 `.claude/skills` 加载同一 `SKILL.md`，通过 Windows shell 调用脚本。
- **WorkBuddy/CodeBuddy**：从 `.codebuddy/skills` 加载同一 `SKILL.md`。能否在会话内运行本地 PowerShell 取决于客户端版本和工具权限。
- **其他 agent**：读取根目录 `AGENTS.md`，再按 `SKILL.md` 调用 `scripts\run_mm.cmd`。

如果 agent 无法执行本地命令，应由用户或宿主先运行 CLI 生成 `transcript.json` 和审计底稿，再让 agent 撰写 `minutes.json`。不得改用云端转写、跳过人工复核或伪造缺失内容。

## 质量说明

结构、术语门禁、数字覆盖、片段覆盖和 DOCX 版式由脚本统一保证。不同模型仍可能在长文理解、专家判断保留、中文表达和问答组织上产生差异。任何 agent 生成正式稿前都必须通过同一 `validate` 校验。
