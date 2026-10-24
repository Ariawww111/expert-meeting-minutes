param(
    [ValidateSet("Codex", "Claude", "WorkBuddy", "All")]
    [string]$Target = "All",
    [ValidateSet("Copy", "Junction")]
    [string]$Mode = "Copy",
    [string]$DestinationRoot = $env:USERPROFILE,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$SkillRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$DestinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)
$SkillName = "expert-meeting-minutes"

$TargetMap = @{
    Codex = Join-Path $DestinationRoot ".codex\skills\$SkillName"
    Claude = Join-Path $DestinationRoot ".claude\skills\$SkillName"
    WorkBuddy = Join-Path $DestinationRoot ".codebuddy\skills\$SkillName"
}

$Targets = if ($Target -eq "All") {
    @("Codex", "Claude", "WorkBuddy")
} else {
    @($Target)
}

$ExcludedFolders = @(".git", "__pycache__", ".pytest_cache")
$ExcludedRelativeFolders = @("tests\qa-output", "tests\smoke-output")
$ExcludedExtensions = @(".pyc", ".mp3", ".m4a", ".wav", ".mp4")

function Assert-SafeTarget {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $allowedPrefix = $DestinationRoot.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($allowedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside DestinationRoot: $fullPath"
    }
    if ((Split-Path -Leaf $fullPath) -ne $SkillName) {
        throw "Refusing to operate on an unexpected skill directory: $fullPath"
    }
    return $fullPath
}

function Copy-SkillTree {
    param(
        [string]$Source,
        [string]$Destination,
        [string]$Relative = ""
    )

    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        $childRelative = if ($Relative) {
            Join-Path $Relative $item.Name
        } else {
            $item.Name
        }

        if ($item.PSIsContainer) {
            if ($ExcludedFolders -contains $item.Name) {
                continue
            }
            $normalized = $childRelative.Replace('/', '\')
            $excludedRelative = $ExcludedRelativeFolders | Where-Object {
                $normalized.Equals($_, [System.StringComparison]::OrdinalIgnoreCase)
            }
            if ($excludedRelative) {
                continue
            }
            Copy-SkillTree -Source $item.FullName -Destination (Join-Path $Destination $item.Name) -Relative $childRelative
            continue
        }

        if ($ExcludedExtensions -contains $item.Extension.ToLowerInvariant()) {
            continue
        }
        $destinationFile = Join-Path $Destination $item.Name
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationFile) | Out-Null
        Copy-Item -LiteralPath $item.FullName -Destination $destinationFile -Force
    }
}

foreach ($agent in $Targets) {
    $destination = Assert-SafeTarget $TargetMap[$agent]
    if (Test-Path -LiteralPath $destination) {
        if (-not $Force) {
            throw "Destination already exists: $destination. Use -Force to update."
        }
        Remove-Item -LiteralPath $destination -Recurse -Force
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    if ($Mode -eq "Junction") {
        New-Item -ItemType Junction -Path $destination -Target $SkillRoot | Out-Null
    } else {
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-SkillTree -Source $SkillRoot -Destination $destination
    }
    Write-Host "[$agent] installed to $destination"
}
