<#
.SYNOPSIS
  Transforma texto em fala (portugues do Brasil) com o Piper, sem internet e so com CPU.
  Gera um .wav e, com -Tocar, ja reproduz.
.EXAMPLE
  .\falar.ps1 "Bom dia. O cofre esta funcionando." -Tocar
  .\falar.ps1 -Arquivo C:\texto.txt -Voz cadu -Saida C:\Users\voce\Desktop\audio.wav
#>
param(
    [Parameter(Position = 0)][string]$Texto,
    [string]$Arquivo,
    [ValidateSet('faber', 'cadu')][string]$Voz = 'faber',
    [string]$Saida,
    [switch]$Tocar
)
. "$PSScriptRoot\comum.ps1"

$modelo = Join-Path $PastaModelos "audio\piper\pt_BR-$Voz-medium.onnx"
if (-not (Test-Path -LiteralPath $modelo)) { throw 'Vozes do Piper nao baixadas. Rode: .\baixar-modelo.ps1 -Id piper-pt-br' }
if (-not $Saida) { $Saida = Join-Path $Raiz ("dev\audio-gerado\fala-{0}.wav" -f (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$uv = Preparar-Uv
$script = Join-Path $Raiz 'dev\ferramentas\falar.py'
$resto = @('--script', $script, '--modelo', $modelo, '--saida', $Saida)
if ($Arquivo) { $resto += @('--arquivo', $Arquivo) } elseif ($Texto) { $resto += $Texto } else { throw 'Informe o texto ou -Arquivo.' }

$env:PYTHONIOENCODING = 'utf-8'
# --offline usa so o cache do SSD; se faltar algum pacote, tenta uma vez com internet.
Executar-Nativo $uv (@('run', '--offline') + $resto)
if ($LASTEXITCODE -ne 0) { Info 'Tentando de novo com internet...'; Executar-Nativo $uv (@('run') + $resto) }
if ($LASTEXITCODE -eq 0) {
    Ok "Audio: $Saida"
    if ($Tocar) { (New-Object System.Media.SoundPlayer $Saida).PlaySync() }
}
