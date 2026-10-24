param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$MmArgs
)

$ErrorActionPreference = "Stop"
$DataRoot = if ($env:EXPERT_MEETING_DATA_DIR) {
    $env:EXPERT_MEETING_DATA_DIR
} else {
    "D:\CodexData\expert-meeting-minutes"
}
$Python = Join-Path $DataRoot "venv312\Scripts\python.exe"
$Mm = Join-Path $PSScriptRoot "mm.py"

if (-not (Test-Path $Python)) {
    throw "未找到本地环境：$Python。请先运行 $PSScriptRoot\setup_env.ps1。"
}

$env:EXPERT_MEETING_DATA_DIR = $DataRoot
$env:MODELSCOPE_CACHE = Join-Path $DataRoot "modelscope"
$env:HF_HOME = Join-Path $DataRoot "huggingface"

& $Python $Mm @MmArgs
exit $LASTEXITCODE
