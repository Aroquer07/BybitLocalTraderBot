# Injects AI_GUIDELINES.md into agent context (sessionStart + beforeSubmitPrompt).
# Project hook — runs from repository root.
$ErrorActionPreference = 'SilentlyContinue'

function Get-GuidelinesPath {
    $candidates = @(
        (Join-Path (Get-Location) 'AI_GUIDELINES.md'),
        (Join-Path $PSScriptRoot '..\..\AI_GUIDELINES.md')
    )
    foreach ($candidate in $candidates) {
        $full = [System.IO.Path]::GetFullPath($candidate)
        if (Test-Path -LiteralPath $full) {
            return $full
        }
    }
    return $null
}

$guidelinesPath = Get-GuidelinesPath
if (-not $guidelinesPath) {
    Write-Output '{}'
    exit 0
}

$content = Get-Content -LiteralPath $guidelinesPath -Raw -Encoding UTF8
$header = @"
## MANDATORY — AI Guidelines (BybitLocalTraderBot)

Apply BEFORE every response in this conversation:
- Open errors (ERR-*) and pending improvements (IMP-*)
- Update AI_GUIDELINES.md when finding bugs or shipping fixes
- README.md is the canonical architecture documentation

---

"@

$payload = [ordered]@{
    additional_context = $header + $content
}

$payload | ConvertTo-Json -Compress | Write-Output
exit 0
