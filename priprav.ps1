# Zkopíruje skripty stavby z 3-jednotka\mapa do cloud-repo\ (zdroj pravdy zůstává 3-jednotka\mapa).
# Spustit před každým nahráním do repozitáře map na GitHubu.
$ErrorActionPreference = 'Stop'
$mapa = Split-Path $PSScriptRoot -Parent
foreach ($f in 'stav_pack.py', 'evropa.py', 'publikuj.py') {
    Copy-Item (Join-Path $mapa $f) (Join-Path $PSScriptRoot $f) -Force
}
Write-Output "cloud-repo pripraven: $PSScriptRoot"
