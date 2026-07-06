# End-of-session hook — enforces AI_GUIDELINES checklist (commit + push mandatory).
# Modes: sessionEnd (inject context) | stop (follow-up if dirty working tree).
param(
    [ValidateSet('sessionEnd', 'stop')]
    [string]$Mode = 'sessionEnd'
)

$ErrorActionPreference = 'SilentlyContinue'

function Get-RepoRoot {
    $candidates = @(
        (Get-Location).Path,
        (Join-Path $PSScriptRoot '..\..')
    )
    foreach ($candidate in $candidates) {
        $full = [System.IO.Path]::GetFullPath($candidate)
        if (Test-Path -LiteralPath (Join-Path $full '.git')) {
            return $full
        }
    }
    return (Get-Location).Path
}

function Get-GuidelinesPath {
    $root = Get-RepoRoot
    $path = Join-Path $root 'AI_GUIDELINES.md'
    if (Test-Path -LiteralPath $path) {
        return $path
    }
    return $null
}

function Get-DirtyFiles {
    param([string]$RepoRoot)
    $porcelain = & git -C $RepoRoot status --porcelain 2>$null
    if (-not $porcelain) {
        return @()
    }
    return @($porcelain | Where-Object { $_ -match '\S' })
}

$repoRoot = Get-RepoRoot
$guidelinesPath = Get-GuidelinesPath
$guidelinesRef = if ($guidelinesPath) { 'AI_GUIDELINES.md' } else { 'AI_GUIDELINES.md (missing — follow project rules)' }

$rules = @"
## MANDATORY - End of session checklist ($guidelinesRef)

You MUST follow AI_GUIDELINES.md before ending this session:

1. **Review** ``git status`` and ``git diff`` - never commit ``.env``, ``data/`` runtime, Telegram sessions, ``.run/``, ``.venv/``
2. **Update AI_GUIDELINES.md** if you found bugs (ERR-*), improvements (IMP-*), or shipped fixes (Solucao block + Resolvidos)
3. **Update README.md** if architecture, API endpoints, or startup flows changed
4. **Commit** with English message: ``fix - ...``, ``feat - ...``, ``docs - ...`` (format in AI_GUIDELINES Versionamento Git)
5. **Push to origin** in the same session - mandatory; do not leave only a local commit
6. If push fails (network/permissions), report in chat and retry

**Absolute rule:** sessions with versionable changes end with ``git commit`` then ``git push``.
"@

if ($Mode -eq 'sessionEnd') {
    $payload = [ordered]@{
        additional_context = $rules
    }
    $payload | ConvertTo-Json -Compress | Write-Output
    exit 0
}

# stop — nudge agent to finish commit+push when working tree is dirty
$dirty = Get-DirtyFiles -RepoRoot $repoRoot
if ($dirty.Count -eq 0) {
    Write-Output '{}'
    exit 0
}

$preview = ($dirty | Select-Object -First 12) -join "`n"
if ($dirty.Count -gt 12) {
    $preview += "`n... (+$($dirty.Count - 12) more)"
}

$followup = @"
$rules

---

**Uncommitted changes detected** ($($dirty.Count) file(s)). Do NOT end the session yet.

Complete now:
1. Review diffs and exclude secrets/runtime files
2. Update AI_GUIDELINES.md / README.md if applicable
3. ``git add`` relevant files -> ``git commit`` -> ``git push origin``

Dirty files:
$preview
"@

$payload = [ordered]@{
    followup_message = $followup
}
$payload | ConvertTo-Json -Compress | Write-Output
exit 0
