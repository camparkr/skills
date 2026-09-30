# setup.ps1 - link the /dry-run skill into Claude Code on Windows, without admin rights.
# Safe to run twice. Usage: powershell -ExecutionPolicy Bypass -File setup.ps1 [-DryRun] [-Uninstall]

param([switch]$DryRun, [switch]$Uninstall)

$ErrorActionPreference = 'Stop'

# The skill folder is skill\, beside this script at the repository root.
$SkillDir = (Join-Path $PSScriptRoot 'skill').TrimEnd('\')
if (-not (Test-Path (Join-Path $SkillDir 'SKILL.md'))) {
    [Console]::Error.WriteLine("No SKILL.md in $SkillDir; run this script from the repository root it came with.")
    exit 1
}
$Link = Join-Path $HOME '.claude\skills\dry-run'
# A copy made by the fallback carries this file, so a later run can tell the copy is ours.
$Marker = '.copied-by-setup'
$Would = if ($DryRun) { 'would be ' } else { '' }

function Invoke-Step([string]$Text, [scriptblock]$Action) {
    if ($DryRun) { Write-Output "  would run: $Text" } else { & $Action }
}

function Get-State {
    $item = Get-Item -LiteralPath $Link -Force -ErrorAction SilentlyContinue
    if (-not $item) { return 'absent' }
    if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') {
        $target = ([string]@($item.Target)[0]) -replace '^\\\\\?\\', ''
        if ($target.TrimEnd('\') -ieq $SkillDir) { return 'ours-link' }
        return 'other'
    }
    $mark = Join-Path $Link $Marker
    if ((Test-Path -LiteralPath $mark) -and ((Get-Content -LiteralPath $mark -Raw).Trim() -ieq $SkillDir)) {
        return 'ours-copy'
    }
    return 'other'
}

function New-Copy {
    Copy-Item -LiteralPath $SkillDir -Destination $Link -Recurse
    Set-Content -LiteralPath (Join-Path $Link $Marker) -Value $SkillDir
}

Write-Output "Claude Code: $Link"
if (-not (Get-Command claude -ErrorAction SilentlyContinue) -and -not (Test-Path (Join-Path $HOME '.claude'))) {
    $Result = 'not installed, skipped'
} else {
    $State = Get-State
    if ($Uninstall) {
        switch ($State) {
            # Directory.Delete without recursion removes the junction only, never the skill folder behind it.
            'ours-link' { Invoke-Step "remove junction $Link" { [IO.Directory]::Delete($Link, $false) }; $Result = "link ${Would}removed" }
            'ours-copy' { Invoke-Step "Remove-Item -Recurse $Link" { Remove-Item -LiteralPath $Link -Recurse -Force }; $Result = "copy ${Would}removed" }
            'other'     { Write-Output '  left alone: it is not a link to, or copy of, this skill folder'; $Result = 'not ours, left alone' }
            default     { $Result = 'nothing to remove' }
        }
    } else {
        switch ($State) {
            'ours-link' { $Result = 'already linked, left as is' }
            'ours-copy' {
                Invoke-Step "refresh copy at $Link" { Remove-Item -LiteralPath $Link -Recurse -Force; New-Copy }
                $Result = "copy ${Would}refreshed; run this script again after each pull"
            }
            'other' {
                Write-Output '  stopped: something else is at this path:'
                Get-Item -LiteralPath $Link -Force | Format-Table Mode, LinkType, FullName -AutoSize | Out-String | Write-Output
                $Result = 'STOPPED, path occupied (see above)'
            }
            default {
                Invoke-Step "New-Item -ItemType Directory $(Split-Path $Link)" { New-Item -ItemType Directory -Force -Path (Split-Path $Link) | Out-Null }
                if ($DryRun) {
                    Write-Output "  would run: New-Item -ItemType Junction -Path $Link -Target $SkillDir"
                    $Result = 'would be linked (junction; a copy if the junction fails)'
                } else {
                    try {
                        New-Item -ItemType Junction -Path $Link -Target $SkillDir | Out-Null
                        $Result = 'linked (junction)'
                    } catch {
                        Write-Output "  junction failed: $($_.Exception.Message)"
                        New-Copy
                        $Result = 'COPIED, not linked: run this script again after each pull to refresh the copy'
                    }
                }
            }
        }
    }
}

Write-Output ''
if ($DryRun) { Write-Output 'Dry run: nothing was changed.' }
Write-Output "Skill folder: $SkillDir"
Write-Output "  Claude Code: $Result"
Write-Output "Date: $(Get-Date -Format 'yyyy-MM-dd')"
