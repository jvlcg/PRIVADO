<#
.SYNOPSIS
  Abre todas as bibliotecas offline (Wikipedia, WikiMed, iFixit...) no navegador com o kiwix-serve,
  em http://127.0.0.1:8081, com busca em todas ao mesmo tempo.
  O script perguntar.ps1 usa este servidor para o modelo responder citando a Wikipedia.
.EXAMPLE
  .\iniciar-biblioteca.ps1
  .\iniciar-biblioteca.ps1 -Rede      # libera para celulares e outros PCs da sua rede
#>
param([int]$Porta = 8081, [switch]$Rede, [switch]$SemNavegador)
. "$PSScriptRoot\comum.ps1"

$exe = Achar-Exe 'kiwix-tools' 'kiwix-serve.exe'
$pastas = @(Join-Path $Raiz 'conhecimento')
$rc = Raiz-Cofre
if ($rc -and (Test-Path -LiteralPath (Join-Path $rc 'conhecimento'))) { $pastas += (Join-Path $rc 'conhecimento') }
$zims = @($pastas | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter '*.zim' -File } | ForEach-Object { $_.FullName })
if ($zims.Count -eq 0) { throw 'Nenhuma biblioteca baixada. Rode: .\baixar-conhecimento.ps1 -Local nucleo' }

$ip = '127.0.0.1'
if ($Rede) { $ip = '0.0.0.0' }
$url = "http://127.0.0.1:$Porta"
if (-not $SemNavegador) {
    $espera = "for (`$i = 0; `$i -lt 120; `$i++) { try { Invoke-WebRequest -UseBasicParsing '$url' -TimeoutSec 2 | Out-Null; Start-Process '$url'; break } catch { Start-Sleep -Seconds 1 } }"
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($espera))
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -EncodedCommand $enc"
}
Titulo 'Biblioteca offline'
foreach ($z in $zims) { Info (Split-Path $z -Leaf) }
Info "Endereco: $url    Para parar: Ctrl+C."
Executar-Nativo $exe (@('--address', $ip, '--port', "$Porta") + $zims)
