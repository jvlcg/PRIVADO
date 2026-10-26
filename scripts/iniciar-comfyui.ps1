<#
.SYNOPSIS
  Abre o ComfyUI portatil (imagem, video, musica e 3D) a partir do SSD, em http://127.0.0.1:8188
  Os modelos vem de modelos\imagem (SSD) e modelos\comfyui (cofre), configurados por instalar-motores.ps1.
  Para comecar: menu "Workflow" > "Browse Templates" e escolha o modelo (ex.: Z-Image Turbo).
.EXAMPLE
  .\iniciar-comfyui.ps1
  .\iniciar-comfyui.ps1 -Rede            # libera para outros aparelhos da sua rede
#>
param([int]$Porta = 8188, [switch]$Rede, [switch]$SemNavegador)
. "$PSScriptRoot\comum.ps1"

$pasta = Pasta-Motor 'comfyui'
if (-not $pasta) { throw 'ComfyUI nao instalado. Rode: .\instalar-motores.ps1 -Motor comfyui' }
$main = Get-ChildItem -LiteralPath $pasta -Recurse -Depth 2 -Filter 'main.py' -File | Where-Object { $_.Directory.Name -eq 'ComfyUI' } | Select-Object -First 1
if (-not $main) { throw "Nao achei ComfyUI\main.py em $pasta" }
$raizPortatil = $main.Directory.Parent.FullName
$python = Join-Path $raizPortatil 'python_embeded\python.exe'

# Entrada, saida e configuracoes ficam fora da pasta da versao (dev\comfyui): atualizar ou limpar
# versoes antigas do ComfyUI nunca apaga o que voce criou.
$dados = Join-Path $Raiz 'dev\comfyui'
foreach ($s in 'input', 'output', 'user', 'temp') { New-Item -ItemType Directory -Force -Path (Join-Path $dados $s) | Out-Null }
$a = @('-s', $main.FullName, '--windows-standalone-build', '--port', "$Porta",
       '--input-directory', (Join-Path $dados 'input'), '--output-directory', (Join-Path $dados 'output'),
       '--user-directory', (Join-Path $dados 'user'), '--temp-directory', (Join-Path $dados 'temp'))
if ($Rede) { $a += @('--listen', '0.0.0.0') }
if ($SemNavegador) { $a += '--disable-auto-launch' }

Titulo 'ComfyUI'
Info "Endereco: http://127.0.0.1:$Porta"
Info 'Para comecar: Workflow > Browse Templates. Para parar: Ctrl+C.'
Push-Location $raizPortatil
[Environment]::CurrentDirectory = $raizPortatil
try { Executar-Nativo $python $a } finally { Pop-Location }
