# guild-switch.ps1 - Hard switch for llama-guild workflow skill triggering (ZCode).
#
# Writes/removes ZCode `skillOverrides` entries ({"<skill path>": {"enable": false}})
# in the user config (~/.zcode/cli/config.json) or a workspace config (<cwd>/.zcode/config.json).
# Disabled skills are removed from the model's context entirely: zero tokens, zero auto-triggering.
#
# Usage:
#   powershell -File guild-switch.ps1 status            # per-skill state (user scope)
#   powershell -File guild-switch.ps1 off               # stop accidental triggering
#   powershell -File guild-switch.ps1 on                # restore the workflow
#   powershell -File guild-switch.ps1 off -Scope workspace   # write <cwd>/.zcode/config.json instead
#
# Note: other tools (Claude Code / Codex / ...) do not expose per-skill disable
# overrides; there the trigger-word hardening in the skills themselves is the
# available mitigation.

param(
    [Parameter(Position = 0)]
    [ValidateSet('on', 'off', 'status')]
    [string]$Action = 'status',
    [ValidateSet('user', 'workspace')]
    [string]$Scope = 'user'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot   # script lives in <repo>\install

if ($Scope -eq 'user') {
    $configPath = Join-Path $env:USERPROFILE '.zcode\cli\config.json'
} else {
    $configPath = Join-Path (Get-Location) '.zcode\config.json'
}

$skillDirs = Get-ChildItem (Join-Path $repo 'skills') -Directory |
    ForEach-Object { $_.FullName }
if (-not $skillDirs) {
    Write-Host "[guild-switch] no skills found under $repo\skills"; exit 1
}

# Read (or initialize) the config while preserving every other key.
$cfg = if (Test-Path $configPath) {
    Get-Content $configPath -Raw | ConvertFrom-Json
} else {
    [pscustomobject]@{}
}
if (-not $cfg.PSObject.Properties['skillOverrides']) {
    $cfg | Add-Member -NotePropertyName skillOverrides -NotePropertyValue ([pscustomobject]@{})
}
$overrides = $cfg.skillOverrides

# Keys registered per skill: the directory and its SKILL.md (covers both
# path-matching implementations ZCode may use).
function Get-Prop($obj, [string]$name) {
    $obj.PSObject.Properties | Where-Object { $_.Name -eq $name } | Select-Object -First 1
}

function Get-KeysFor([string]$dir) {
    @($dir, (Join-Path $dir 'SKILL.md'))
}

function Set-Disabled([string]$dir, [bool]$disabled) {
    foreach ($k in Get-KeysFor $dir) {
        $prop = Get-Prop $overrides $k
        if ($disabled) {
            if ($prop) { $prop.Value = [pscustomobject]@{ enable = $false } }
            else { $overrides | Add-Member -NotePropertyName $k -NotePropertyValue ([pscustomobject]@{ enable = $false }) }
        } elseif ($prop) {
            $overrides.PSObject.Properties.Remove($k)
        }
    }
}

function Test-Disabled([string]$dir) {
    foreach ($k in Get-KeysFor $dir) {
        $prop = Get-Prop $overrides $k
        if ($prop -and $prop.Value.enable -eq $false) { return $true }
    }
    return $false
}

switch ($Action) {
    'off' {
        foreach ($d in $skillDirs) { Set-Disabled $d $true }
        $cfg | ConvertTo-Json -Depth 16 | Set-Content $configPath -Encoding UTF8
        Write-Host "[guild-switch] OFF ($Scope scope): workflow skills disabled in $configPath"
        Write-Host "[guild-switch] they no longer load into the model context; run 'on' to restore."
    }
    'on' {
        foreach ($d in $skillDirs) { Set-Disabled $d $false }
        $cfg | ConvertTo-Json -Depth 16 | Set-Content $configPath -Encoding UTF8
        Write-Host "[guild-switch] ON ($Scope scope): workflow skills active again."
    }
    'status' {
        Write-Host "[guild-switch] scope=$Scope config=$configPath"
        foreach ($d in $skillDirs) {
            $state = if (Test-Disabled $d) { 'DISABLED' } else { 'active  ' }
            Write-Host ("  [{0}] {1}" -f $state, (Split-Path -Leaf $d))
        }
        Write-Host "[guild-switch] flip with: guild-switch.ps1 on|off -Scope $Scope"
    }
}
