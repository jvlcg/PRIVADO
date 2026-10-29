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
#>
param(
    [Parameter(Position = 0)][string]$Pergunta,
    [string]$Indexar,
    [string]$Buscar,
    [string]$Livros,
    [string]$Modelo = 'gemma-4-26b-a4b'
)
. "$PSScriptRoot\comum.ps1"
Bloquear-SeModoJogo 'o Perguntar com fonte'

$uv = Preparar-Uv
$sabio = Join-Path $Raiz 'dev\ferramentas\sabio.py'
$inicio = Get-Date
if (-not $Indexar) { Mostrar-Estimativa 'perguntar' }
if ($Indexar) { $a = @('indexar', $Indexar) }
elseif ($Buscar) { $a = @('buscar', $Buscar, '--modelo', $Modelo) }
elseif ($Pergunta) {
    $a = @('perguntar', $Pergunta, '--modelo', $Modelo)
    if ($Livros) { $a += @('--livros', $Livros) }
} else { throw 'Informe uma pergunta, -Indexar <pasta> ou -Buscar <pergunta>.' }

# --offline usa so o que ja esta no cache do SSD; sem cache, tenta a internet uma vez.
$env:PYTHONIOENCODING = 'utf-8'
Executar-Nativo $uv (@('run', '--offline', '--script', $sabio) + $a)
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1) { Executar-Nativo $uv (@('run', '--script', $sabio) + $a) }
Mostrar-GastoFinal 'perguntar' $inicio
