# install-memory.ps1
# Run once after cloning on a new machine (safe to re-run) to install Claude memory files.
# Usage (from repo root):  .\.claude\install-memory.ps1

$repoRoot  = Split-Path $PSScriptRoot -Parent
$repoRoot  = Resolve-Path $repoRoot

# Claude encodes the project path by replacing \ and : with -
$encoded   = $repoRoot.Path -replace '[:\\]', '-'
$dest      = "$env:USERPROFILE\.claude\projects\$encoded\memory"

New-Item -ItemType Directory -Path $dest -Force | Out-Null

# Topic files: repo copies are the shared, reviewed versions
Get-ChildItem "$PSScriptRoot\memory\*.md" | Where-Object Name -ne 'MEMORY.md' |
    ForEach-Object { Copy-Item $_.FullName $dest -Force }

# Index: merge, don't overwrite — keeps pointers to machine-local memories (user profile,
# permissions, tool paths) that are deliberately not committed
$index = Join-Path $dest 'MEMORY.md'
$repoIndex = Get-Content "$PSScriptRoot\memory\MEMORY.md"
if (Test-Path $index) {
    $existing = Get-Content $index
    $missing  = $repoIndex | Where-Object { $_ -like '- *' -and $existing -notcontains $_ }
    if ($missing) { Add-Content $index $missing }
} else {
    Set-Content $index $repoIndex
}

Write-Host "Installed $(( Get-ChildItem $dest -Filter *.md ).Count) memory files to:"
Write-Host "  $dest"
