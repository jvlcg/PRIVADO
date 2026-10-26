<#
.SYNOPSIS
  Transcreve um arquivo de audio com o whisper.cpp e o modelo Whisper do acervo.
  Gera .txt e .srt (legenda) ao lado do audio.
.EXAMPLE
  .\transcrever.ps1 -Audio C:\Users\voce\Desktop\reuniao.wav
  .\transcrever.ps1 -Audio entrevista.wav -Idioma en
.NOTES
  O whisper.cpp le WAV 16 kHz com certeza. Para MP3/M4A, converta antes com o ffmpeg:
  ffmpeg -i entrada.mp3 -ar 16000 -ac 1 saida.wav
#>
param(
    [Parameter(Mandatory = $true)][string]$Audio,
    [string]$Idioma = 'pt',
    [string]$Modelo = 'whisper-large-v3-turbo'
)
. "$PSScriptRoot\comum.ps1"

$cat = Ler-Catalogo
$m = $cat.modelos | Where-Object { $_.id -eq $Modelo } | Select-Object -First 1
if (-not $m) { throw "Modelo '$Modelo' nao esta no catalogo." }
$bin = Caminho-Destino $m $m.arquivos[0]
if (-not (Test-Path -LiteralPath $bin)) { throw "Modelo nao baixado. Rode: .\baixar-modelo.ps1 -Id $Modelo" }
$exe = Achar-Exe 'whisper.cpp' 'whisper-cli.exe'
$arqAudio = (Resolve-Path -LiteralPath $Audio).Path
$saida = [IO.Path]::ChangeExtension($arqAudio, $null).TrimEnd('.')

Titulo "Transcrevendo $(Split-Path $arqAudio -Leaf)"
Executar-Nativo $exe @('-m', $bin, '-l', $Idioma, '-f', $arqAudio, '-otxt', '-osrt', '-of', $saida)
if ($LASTEXITCODE -eq 0) { Ok "Pronto: $saida.txt e $saida.srt" }
