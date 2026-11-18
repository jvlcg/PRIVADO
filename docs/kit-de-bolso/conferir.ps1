# Cofre de bolso: confere cada arquivo do pen drive pela impressao digital (SHA-256) anotada na montagem.
# Roda em qualquer Windows (PowerShell 5.1 ou mais novo). Abra pelo conferir.cmd, ao lado.
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$raiz = Split-Path -Parent $PSScriptRoot
$lista = Join-Path $PSScriptRoot 'SHA256SUMS.txt'
if (-not (Test-Path -LiteralPath $lista)) { Write-Host '  Nao achei Programas\SHA256SUMS.txt.' -ForegroundColor Red; exit 1 }
$linhas = @(Get-Content -LiteralPath $lista -Encoding UTF8 | Where-Object { $_ -match '^[0-9a-f]{64}  \S' })
$ok = 0; $ruins = @(); $i = 0; $inicio = Get-Date
Write-Host ''
Write-Host "  Conferindo $($linhas.Count) arquivos (os grandes levam alguns minutos)..." -ForegroundColor Cyan
foreach ($l in $linhas) {
    $i++
    $esperado = $l.Substring(0, 64)
    $rel = $l.Substring(66)
    $caminho = Join-Path $raiz ($rel -replace '/', '\')
    Write-Host ("  [{0}/{1}] {2}" -f $i, $linhas.Count, $rel)
    if (-not (Test-Path -LiteralPath $caminho)) { $ruins += "FALTANDO: $rel"; continue }
    $atual = (Get-FileHash -Algorithm SHA256 -LiteralPath $caminho).Hash.ToLower()
    if ($atual -eq $esperado) { $ok++ } else { $ruins += "ESTRAGADO: $rel" }
}
$min = [math]::Round(((Get-Date) - $inicio).TotalMinutes, 1)
Write-Host ''
if ($ruins.Count -eq 0) {
    Write-Host "  Tudo certo: $ok arquivos conferidos em $min min." -ForegroundColor Green
    exit 0
}
Write-Host "  $($ruins.Count) arquivo(s) com problema:" -ForegroundColor Red
$ruins | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
Write-Host '  Copie de novo do cofre de casa (kit de bolso, no menu) ou baixe a biblioteca outra vez.'
exit 2
