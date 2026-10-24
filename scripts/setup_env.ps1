param(
    [string]$DataRoot = "D:\CodexData\expert-meeting-minutes",
    [switch]$SkipModelWarmup
)

$ErrorActionPreference = "Stop"
$SkillRoot = Split-Path -Parent $PSScriptRoot
$VenvRoot = Join-Path $DataRoot "venv312"
$Python = Join-Path $VenvRoot "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "modelscope") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "huggingface") | Out-Null

if (-not (Test-Path $Python)) {
    Write-Host "Creating isolated environment at $VenvRoot"
    $BasePython = $env:CODEX_RUNTIME_PYTHON
    if (-not $BasePython) {
        $Candidate = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
        if (Test-Path $Candidate) {
            $BasePython = $Candidate
        }
    }
    if (-not $BasePython) {
        $BasePython = (Get-Command python -ErrorAction Stop).Source
    }
    Write-Host "Using base Python: $BasePython"
    & $BasePython -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) { throw "Creating virtual environment failed with exit code $LASTEXITCODE" }
}

$env:EXPERT_MEETING_DATA_DIR = $DataRoot
$env:MODELSCOPE_CACHE = Join-Path $DataRoot "modelscope"
$env:HF_HOME = Join-Path $DataRoot "huggingface"

Write-Host "Installing CPU PyTorch"
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE" }
& $Python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed with exit code $LASTEXITCODE" }

Write-Host "Installing FunASR and document dependencies"
& $Python -m pip install --no-cache-dir --retries 10 --timeout 60 -r (Join-Path $SkillRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "FunASR dependency installation failed with exit code $LASTEXITCODE" }

if (-not $SkipModelWarmup) {
    Write-Host "Downloading and validating FunASR models"
    & $Python -c "from funasr import AutoModel; AutoModel(model='fsmn-vad', device='cpu', disable_update=True, trust_remote_code=False); AutoModel(model='paraformer-zh', vad_model='fsmn-vad', punc_model='ct-punc', spk_model='cam++', device='cpu', disable_update=True, trust_remote_code=False)"
    if ($LASTEXITCODE -ne 0) { throw "FunASR model warmup failed with exit code $LASTEXITCODE" }
}

Write-Host "Environment ready."
Write-Host "Set EXPERT_MEETING_DATA_DIR=$DataRoot for future shells."
Write-Output $Python
