# install-memory.ps1
# Run once after cloning on a new machine to install Claude memory files.
# Usage (from repo root):  .\.claude\install-memory.ps1

$repoRoot  = Split-Path $PSScriptRoot -Parent
$repoRoot  = Resolve-Path $repoRoot

# Claude encodes the project path by replacing \ and : with -
$encoded   = $repoRoot.Path -replace '[:\\]', '-'
$dest      = "$env:USERPROFILE\.claude\projects\$encoded\memory"

New-Item -ItemType Directory -Path $dest -Force | Out-Null

Copy-Item "$PSScriptRoot\memory\*.md" $dest -Force

Write-Host "Installed $(( Get-ChildItem $dest -Filter *.md ).Count) memory files to:"
Write-Host "  $dest"
