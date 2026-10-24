# 免费本地环境与模型许可

## 安装

当前机器建议在 D 盘安装，避免占用 C 盘：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "<skill-dir>\scripts\setup_env.ps1"
```

脚本会：

- 使用 Codex 随附的稳定 Python 3.12 创建 `D:\CodexData\expert-meeting-minutes\venv312`。
- 安装 CPU 版 PyTorch、FunASR、python-docx、imageio-ffmpeg 和测试依赖。
- 把模型缓存放在 `D:\CodexData\expert-meeting-minutes\modelscope`。
- 首次下载并加载 `fsmn-vad`、`paraformer-zh`、`ct-punc`、`cam++`。

安装完成后，在调用 `mm.py` 前使用隔离环境：

```powershell
$env:EXPERT_MEETING_DATA_DIR = "D:\CodexData\expert-meeting-minutes"
$env:MODELSCOPE_CACHE = "D:\CodexData\expert-meeting-minutes\modelscope"
$env:HF_HOME = "D:\CodexData\expert-meeting-minutes\huggingface"
& "<skill-dir>\scripts\run_mm.ps1" setup-check --json
```

## 模型

- `paraformer-zh`：中文和英文长音频识别，约 220M 参数。
- `fsmn-vad`：语音端点检测，用于检查转写覆盖。
- `ct-punc`：中文和英文标点恢复。
- `cam++`：匿名说话人嵌入，用于录音内说话人聚类。

`CAM++` 不识别真实姓名，也不保证跨录音编号一致。正式纪要不需要说话人姓名。

## 许可

- FunASR 工具包代码：MIT。
- 模型权重：以对应模型卡条款为准。官方 `paraformer-zh` 相关示例链接 FunASR Model Open Source License Agreement 1.1；使用和分享时应保留来源、作者和模型名称。
- 项目主页：https://github.com/modelscope/FunASR
- 模型许可：https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE

## 常见问题

- `funasr` 导入失败：用 `run_mm.ps1` 调用，确认 D 盘 `venv312` 完整存在。
- 首次下载失败：检查网络或 ModelScope 镜像；模型缓存不得写到空间不足的 C 盘。
- 内存不足：本 skill 以 10 分钟分片转写；不要同时处理多个录音。
- 多声道：必须明确选择 `--channel mix` 或具体声道。不能默认只处理第一轨。
- 转写有错：用时间戳回听，在 `review.json` 中确认修正；不要静默猜测。
