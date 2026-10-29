<#
.SYNOPSIS
  Abre um modelo do catalogo no llama-server:
    - chat no navegador em http://127.0.0.1:8080
    - API compativel com OpenAI em http://127.0.0.1:8080/v1 (VS Code, Continue, Cline, Open WebUI...)
.EXAMPLE
  .\iniciar-chat.ps1                                   # Gemma 4 12B
  .\iniciar-chat.ps1 -Id qwen3-coder-next -Contexto 65536
  .\iniciar-chat.ps1 -Id gemma-4-26b-a4b -Rede         # libera para outros aparelhos da sua rede
  .\iniciar-chat.ps1 -Id qwen3.8-27b -Extra '--temp 0.6'
.NOTES
  Usa a mesma chave de acesso do iniciar-servidor.ps1 (catalogo\chave-api.txt); -SemChave desliga.
#>
param(
    [string]$Id = 'gemma-4-12b',
    [int]$Contexto = 0,
    [int]$Porta = 8080,
    [switch]$Rede,
    [switch]$SemNavegador,
    [string]$Extra = '',
    [switch]$SemChave
)
. "$PSScriptRoot\comum.ps1"

$cat = Ler-Catalogo
$m = $cat.modelos | Where-Object { $_.id -eq $Id -and $_.motor -eq 'llama.cpp' } | Select-Object -First 1
if (-not $m) {
    Write-Host 'Modelos que abrem no chat:'
    $cat.modelos | Where-Object { $_.motor -eq 'llama.cpp' -and $_.status -eq 'baixar' } |
        ForEach-Object { Write-Host "  $($_.id)  ($($_.nome))" }
    throw "Id '$Id' nao e um modelo de chat do catalogo."
}

$arquivos = @($m.arquivos | ForEach-Object { Caminho-Destino $m $_ })
$modelo = $arquivos | Where-Object { (Split-Path $_ -Leaf) -notmatch '^(mmproj|mtp-)' -and $_ -match '\.gguf$' } | Select-Object -First 1
$mmproj = $arquivos | Where-Object { (Split-Path $_ -Leaf) -match '^mmproj' } | Select-Object -First 1
$mtp = $arquivos | Where-Object { (Split-Path $_ -Leaf) -match '^mtp-' -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not (Test-Path -LiteralPath $modelo)) { throw "Modelo ainda nao baixado. Rode: .\baixar-modelo.ps1 -Id $Id" }

$exe = Achar-Exe 'llama.cpp' 'llama-server.exe'
$ctx = $Contexto
if ($ctx -le 0) { $ctx = [int]$m.contexto }
if ($ctx -le 0) { $ctx = 16384 }
$ip = '127.0.0.1'
if ($Rede) { $ip = '0.0.0.0' }

# O llama-server distribui sozinho as camadas entre a GPU e a RAM (--fit, ligado por padrao),
# deixando na placa o maximo que couber. Por isso nao fixamos -ngl aqui.
$a = @('-m', $modelo, '-c', "$ctx", '--host', $ip, '--port', "$Porta", '--alias', $m.id, '--cors-origins', 'localhost')
if ($mmproj -and (Test-Path -LiteralPath $mmproj)) { $a += @('--mmproj', $mmproj) }
# Cabeca MTP: preve varios tokens de uma vez (medido: Qwen3.8 27B +76%, Gemma 4 26B +21%).
if ($mtp) { $a += @('--spec-type', 'draft-mtp', '--spec-draft-model', $mtp) }
if ($m.args) { $a += ($m.args -split '\s+') }
if ($Extra) { $a += ($Extra -split '\s+') }

$url = "http://127.0.0.1:$Porta"
$ehEmbedding = [string]$m.args -match '--embedding'
if (-not $SemNavegador -and -not $ehEmbedding) {
    # Abre o navegador quando o modelo terminar de carregar.
    $espera = "for (`$i = 0; `$i -lt 900; `$i++) { try { Invoke-WebRequest -UseBasicParsing '$url/health' -TimeoutSec 2 | Out-Null; Start-Process '$url'; break } catch { Start-Sleep -Seconds 1 } }"
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($espera))
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -EncodedCommand $enc"
}

Titulo $m.nome
Info "Arquivo:  $(Caminho-Relativo $modelo)"
if ($ehEmbedding) { Info "API de embeddings: $url/v1/embeddings" } else { Info "Chat:     $url" }
Info "API:      $url/v1   (nome do modelo: $($m.id))"
if (-not $SemChave) {
    $chaveApi = Chave-Api
    $a += @('--api-key-file', $ArquivoChave)
    Info "Chave:    $chaveApi   (o chat pede uma vez; outros programas: campo API key)"
    if (-not $SemNavegador -and -not $ehEmbedding) { try { Set-Clipboard -Value $chaveApi; Info '          ja copiada: cole com Ctrl+V quando o chat pedir.' } catch {} }
}
Info 'Para parar: Ctrl+C nesta janela.'
Write-Host ''
Executar-Nativo $exe $a
