<#
.SYNOPSIS
  Central do Cofre: painel no navegador (http://127.0.0.1:8070) que mostra o que esta ligado, liga
  cada servico com um clique, mostra os modelos na memoria e o consumo da placa, e fecha tudo.
  So atende este PC. Se a Central ja estiver aberta, so abre o navegador.
.EXAMPLE
  .\central.ps1
  .\central.ps1 -SemNavegador
#>
param([int]$Porta = 8070, [switch]$SemNavegador)
. "$PSScriptRoot\comum.ps1"

$url = "http://127.0.0.1:$Porta"
$aberta = $false
try { Invoke-WebRequest -UseBasicParsing "$url/health" -TimeoutSec 2 | Out-Null; $aberta = $true } catch {}
if ($aberta) {
    if (-not $SemNavegador) { Start-Process $url }
    Ok "A Central ja esta aberta: $url"
    return
}

if (-not $SemNavegador) {
    $espera = "for (`$i = 0; `$i -lt 60; `$i++) { try { Invoke-WebRequest -UseBasicParsing '$url/health' -TimeoutSec 2 | Out-Null; Start-Process '$url'; break } catch { Start-Sleep -Seconds 1 } }"
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($espera))
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -EncodedCommand $enc"
}

$uv = Preparar-Uv
Titulo 'Central do Cofre'
Info "Painel: $url"
Info 'Para parar a Central: Ctrl+C ou feche esta janela (os servicos ligados continuam).'
$env:PYTHONIOENCODING = 'utf-8'
Executar-Nativo $uv @('run', '--offline', '--script', (Join-Path $Raiz 'dev\ferramentas\central.py'), '--porta', "$Porta")
