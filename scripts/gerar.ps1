<#
.SYNOPSIS
  Gera imagem, video ou animacao pelo ComfyUI do cofre, direto do terminal (sem abrir a interface).
  Usa os fluxos prontos de dev\configs\comfyui e salva o resultado em dev\midia-gerada.
  O ComfyUI precisa estar aberto (menu, opcao 4, ou iniciar-comfyui.ps1).
.EXAMPLE
  .\gerar.ps1 -Imagem "um farol na praia ao por do sol, foto realista"
  .\gerar.ps1 -Imagem "retrato de um astronauta" -Vertical
  .\gerar.ps1 -Video "ondas batendo nas pedras ao amanhecer" -Segundos 3
  .\gerar.ps1 -Animar -Foto C:\fotos\pessoa.png -Movimento C:\videos\danca.mp4 -Descricao "uma mulher de casaco amarelo"
.NOTES
  Escreva as descricoes em ingles para melhor resultado (os modelos foram treinados mais em ingles).
  Tempos medidos na RTX 4070: imagem ~25 s; video de 2 s ~9 min; animacao de 81 quadros ~15 min.
#>
param(
    [string]$Imagem,
    [string]$Video,
    [int]$Segundos = 2,
    [switch]$Vertical,
    [switch]$Animar,
    [string]$Foto,
    [string]$Movimento,
    [string]$Descricao = 'A person',
    [long]$Semente = -1
)
. "$PSScriptRoot\comum.ps1"

$url = 'http://127.0.0.1:8188'
try { Invoke-WebRequest -UseBasicParsing "$url/system_stats" -TimeoutSec 3 | Out-Null }
catch { throw 'O ComfyUI nao esta aberto. Abra pelo menu (opcao 4) ou rode iniciar-comfyui.ps1.' }

$pastaFluxos = Join-Path $Raiz 'dev\configs\comfyui'
$saida = Join-Path $Raiz 'dev\midia-gerada'
New-Item -ItemType Directory -Force -Path $saida | Out-Null
# Mesmas pastas que o iniciar-comfyui.ps1 passa ao ComfyUI.
$pastaEntrada = Join-Path $Raiz 'dev\comfyui\input'
$pastaSaidaComfy = Join-Path $Raiz 'dev\comfyui\output'
if ($Semente -lt 0) { $Semente = Get-Random -Minimum 1 -Maximum 2147483647 }

function Ler-Fluxo($nome) { return ([IO.File]::ReadAllText((Join-Path $pastaFluxos $nome), [Text.Encoding]::UTF8) | ConvertFrom-Json) }

if ($Imagem) {
    $p = Ler-Fluxo 'z-image-turbo-api.json'
    $p.'5'.inputs.text = $Imagem
    $p.'8'.inputs.seed = $Semente
    if ($Vertical) { $p.'7'.inputs.width = 768; $p.'7'.inputs.height = 1344 }
    $tipo = 'Imagem (Z-Image-Turbo)'
} elseif ($Video) {
    $p = Ler-Fluxo 'wan-2.2-5b-video-api.json'
    $p.'5'.inputs.text = $Video
    $p.'8'.inputs.seed = $Semente
    # O Wan usa 4n+1 quadros a 24 por segundo.
    $p.'7'.inputs.length = [int](4 * [math]::Ceiling(($Segundos * 24) / 4) + 1)
    if ($Vertical) { $p.'7'.inputs.width = 704; $p.'7'.inputs.height = 1280 }
    $tipo = "Video de $Segundos s (Wan 2.2 5B)"
} elseif ($Animar) {
    if (-not $Foto -or -not $Movimento) { throw 'Para animar, informe -Foto (imagem da pessoa) e -Movimento (video com o movimento).' }
    $carimbo = Get-Date -Format 'yyyyMMdd-HHmmss'
    $nomeFoto = "animar-$carimbo$([IO.Path]::GetExtension($Foto))"
    $nomeVideo = "animar-$carimbo$([IO.Path]::GetExtension($Movimento))"
    Copy-Item -LiteralPath $Foto -Destination (Join-Path $pastaEntrada $nomeFoto) -Force
    Copy-Item -LiteralPath $Movimento -Destination (Join-Path $pastaEntrada $nomeVideo) -Force
    $p = Ler-Fluxo 'wan-animate-2-api.json'
    $p.'189'.inputs.image = $nomeFoto
    $p.'240'.inputs.file = $nomeVideo
    $p.'672:582'.inputs.text = "Character Description: $Descricao`nBackground description: same background as the reference image"
    $p.'672:585'.inputs.text = "$Descricao moving exactly like the person in the reference video, background stationary"
    $p.'672:597'.inputs.noise_seed = $Semente
    $p.'246'.inputs.filename_prefix = 'cofre/animacao'
    $p.'292'.inputs.filename_prefix = 'cofre/animacao-comparacao'
    $tipo = 'Animacao (Wan Animate 2)'
} else {
    throw 'Escolha -Imagem "...", -Video "..." ou -Animar -Foto ... -Movimento ...'
}

Titulo $tipo
$corpo = @{ prompt = $p; client_id = 'cofre-gerar' } | ConvertTo-Json -Depth 30
$r = Invoke-RestMethod -Uri "$url/prompt" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($corpo))
$id = $r.prompt_id
Info "Na fila do ComfyUI (semente $Semente). Acompanhe tambem em $url"
$inicio = Get-Date
while ($true) {
    Start-Sleep -Seconds 3
    $h = Invoke-RestMethod "$url/history/$id" -TimeoutSec 30
    $res = $h.$id
    if ($res -and $res.status.completed) { break }
    if ($res -and $res.status.status_str -eq 'error') { break }
    Write-Host ("`r       gerando... {0:mm\:ss}" -f ((Get-Date) - $inicio)) -NoNewline
}
Write-Host ''
if ($res.status.status_str -ne 'success') {
    $msg = ($res.status.messages | Where-Object { $_[0] -eq 'execution_error' } | ForEach-Object { $_[1].exception_message }) -join ' '
    throw "O ComfyUI falhou: $msg"
}
foreach ($no in $res.outputs.PSObject.Properties) {
    foreach ($arq in @($no.Value.images) + @($no.Value.videos) | Where-Object { $_ -and $_.filename }) {
        $origem = Join-Path (Join-Path $pastaSaidaComfy $arq.subfolder) $arq.filename
        $destino = Join-Path $saida $arq.filename
        Copy-Item -LiteralPath $origem -Destination $destino -Force
        Ok ("{0}  ({1:mm\:ss})" -f (Caminho-Relativo $destino), ((Get-Date) - $inicio))
    }
}
