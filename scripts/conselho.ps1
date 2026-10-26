<#
.SYNOPSIS
  Conselho de IAs: varios modelos do acervo respondem a mesma pergunta, podem debater entre si,
  e um relator escreve a resposta final dizendo onde houve consenso e onde houve divergencia.
  Tudo offline. Cada deliberacao vira uma ata em dev\conselho\ (o que cada IA disse).
.EXAMPLE
  .\conselho.ps1 "qual a forma mais segura de guardar agua potavel por anos?"
  .\conselho.ps1 "por que este script da erro? ..." -Debate
  .\conselho.ps1 "decisao importante..." -Profundo       # debate + relator mais forte (~20 min)
  .\conselho.ps1 "o que diz esta placa?" -Imagem C:\fotos\placa.jpg
  .\conselho.ps1 "..." -Membros gemma-4-26b-a4b,gpt-oss-20b -Relator qwen3.8-27b -Pensar muito
  .\conselho.ps1 -Servir      # painel em http://127.0.0.1:8090 + API compativel com OpenAI
.NOTES
  O time padrao, o relator e os especialistas por assunto ficam em catalogo\modelos.json, secao "conselho".
#>
param(
    [Parameter(Position = 0)][string]$Pergunta,
    [switch]$Debate,
    [switch]$Profundo,
    [ValidateSet('nao', 'pouco', 'muito')][string]$Pensar = 'pouco',
    [ValidateSet('auto', 'sim', 'nao')][string]$Fontes = 'auto',
    [string[]]$Membros,
    [string]$Relator,
    [string]$Imagem,
    [switch]$Detalhes,
    [switch]$Servir,
    [int]$Porta = 8090,
    [switch]$Rede,
    [switch]$SemNavegador
)
. "$PSScriptRoot\comum.ps1"

function Esperar-Url($url, $segundos) {
    for ($i = 0; $i -lt $segundos; $i++) {
        try { Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 2 | Out-Null; return $true } catch { Start-Sleep -Seconds 1 }
    }
    return $false
}

if (-not $Servir -and -not $Pergunta) { throw 'Informe uma pergunta ou use -Servir.' }

# O conselho conversa com o servidor de modelos (porta 8080). Se estiver fechado, abre um em outra
# janela com um modelo carregado por vez: cada membro usa a placa de video inteira.
if (-not (Esperar-Url 'http://127.0.0.1:8080/health' 1)) {
    Info 'Abrindo o servidor de modelos em outra janela...'
    Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\iniciar-servidor.ps1`" -SemNavegador -Carregados 1"
    if (-not (Esperar-Url 'http://127.0.0.1:8080/health' 180)) { throw 'O servidor de modelos nao abriu. Rode iniciar-servidor.ps1 para ver o erro.' }
}
if ($Fontes -eq 'sim' -and -not (Esperar-Url 'http://127.0.0.1:8081' 1)) {
    Info 'Abrindo a biblioteca offline (Kiwix) em outra janela...'
    Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\iniciar-biblioteca.ps1`" -SemNavegador"
    [void](Esperar-Url 'http://127.0.0.1:8081' 120)
}

$uv = Preparar-Uv
$conselho = Join-Path $Raiz 'dev\ferramentas\conselho.py'
if ($Servir) {
    $a = @('servir', '--porta', "$Porta")
    if ($Rede) { $a += '--rede' }
    if (-not $SemNavegador) {
        $url = "http://127.0.0.1:$Porta"
        $espera = "for (`$i = 0; `$i -lt 120; `$i++) { try { Invoke-WebRequest -UseBasicParsing '$url/health' -TimeoutSec 2 | Out-Null; Start-Process '$url'; break } catch { Start-Sleep -Seconds 1 } }"
        $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($espera))
        Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -EncodedCommand $enc"
    }
    Titulo 'Conselho de IAs'
} else {
    $a = @('perguntar', $Pergunta, '--pensar', $Pensar, '--fontes', $Fontes)
    if ($Debate) { $a += '--debate' }
    if ($Profundo) { $a += '--profundo' }
    if ($Detalhes) { $a += '--detalhes' }
    if ($Membros) { $a += @('--membros', (($Membros | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ }) -join ',')) }
    if ($Relator) { $a += @('--relator', $Relator) }
    if ($Imagem) { $a += @('--imagem', (Resolve-Path -LiteralPath $Imagem).Path) }
}

$env:PYTHONIOENCODING = 'utf-8'
Executar-Nativo $uv (@('run', '--offline', '--script', $conselho) + $a)
