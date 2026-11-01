<#
.SYNOPSIS
  Pergunte e receba resposta com fonte, sem internet: busca nas bibliotecas offline (Wikipedia,
  WikiMed, iFixit...) ou nos seus documentos indexados, e o modelo responde citando [1], [2]...
  Precisa de iniciar-servidor.ps1 (modelos) e iniciar-biblioteca.ps1 (Kiwix) abertos.
.EXAMPLE
  .\perguntar.ps1 "como purificar agua para beber?"
  .\perguntar.ps1 "how to fix a leaking faucet" -Livros ifixit_pt_all_2026-03
  .\perguntar.ps1 -Indexar C:\Users\voce\Documents\manuais
  .\perguntar.ps1 -Buscar "qual a garantia do inversor solar?"
  .\perguntar.ps1 "..." -Modelo qwen3.8-27b
  .\perguntar.ps1 "torniquete" -Modo buscar      # so a biblioteca, sem IA (quase nada de energia)
  .\perguntar.ps1 "capital da Bolivia" -Modo rapida   # IA pequena, sem fontes (~1 Wh)
  Pergunta repetida mostra a resposta guardada (0 Wh); -DeNovo pergunta outra vez.
#>
param(
    [Parameter(Position = 0)][string]$Pergunta,
    [string]$Indexar,
    [string]$Buscar,
    [string]$Livros,
    [string]$Modelo = 'gemma-4-26b-a4b',
    [ValidateSet('fonte', 'rapida', 'buscar')][string]$Modo = 'fonte',
    [switch]$DeNovo
)
. "$PSScriptRoot\comum.ps1"
Bloquear-SeModoJogo 'o Perguntar com fonte'

$uv = Preparar-Uv
$sabio = Join-Path $Raiz 'dev\ferramentas\sabio.py'
$inicio = Get-Date
$tarefa = @{ fonte = 'perguntar'; rapida = 'rapida'; buscar = 'buscar' }[$Modo]
if (-not $Indexar) { Mostrar-Estimativa $tarefa }
if ($Indexar) { $a = @('indexar', $Indexar) }
elseif ($Buscar) { $a = @('buscar', $Buscar, '--modelo', $Modelo) }
elseif ($Pergunta) {
    $a = @('perguntar', $Pergunta, '--modelo', $Modelo, '--modo', $Modo)
    if ($Livros) { $a += @('--livros', $Livros) }
    if ($DeNovo) { $a += '--de-novo' }
} else { throw 'Informe uma pergunta, -Indexar <pasta> ou -Buscar <pergunta>.' }

# --offline usa so o que ja esta no cache do SSD; sem cache, tenta a internet uma vez.
$env:PYTHONIOENCODING = 'utf-8'
Executar-Nativo $uv (@('run', '--offline', '--script', $sabio) + $a)
# Saida 10 = resposta guardada (pergunta repetida): nada foi ligado, nao ha gasto a anotar.
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1 -and $LASTEXITCODE -ne 10) { Executar-Nativo $uv (@('run', '--script', $sabio) + $a) }
if ($LASTEXITCODE -eq 10) { Write-Host '  Gasto: 0 Wh (resposta guardada).' -ForegroundColor DarkYellow }
else { Mostrar-GastoFinal $tarefa $inicio }
