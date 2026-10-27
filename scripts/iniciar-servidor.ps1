<#
.SYNOPSIS
  Servidor unico com TODOS os modelos de chat e embeddings baixados (modo roteador do llama-server).
  Escolha o modelo no menu do chat (http://127.0.0.1:8080) ou pelo campo "model" da API.
  O servidor carrega o modelo pedido na hora e descarrega o mais antigo quando passa do limite.
  Depois de 15 minutos sem uso, o modelo sai da memoria sozinho e volta na proxima pergunta.
.EXAMPLE
  .\iniciar-servidor.ps1                 # ate 2 modelos carregados ao mesmo tempo
  .\iniciar-servidor.ps1 -Carregados 1   # so um por vez (mais VRAM para cada um)
  .\iniciar-servidor.ps1 -DormirMinutos 0  # nunca tira o modelo da memoria por inatividade
  .\iniciar-servidor.ps1 -Rede           # libera para outros aparelhos da sua rede
.NOTES
  Clientes (VS Code/Continue, Cline, Open WebUI, Aider): base URL http://127.0.0.1:8080/v1,
  chave de API qualquer texto, modelo = id do catalogo (ex.: qwen3-coder-next).
#>
param(
    [int]$Porta = 8080,
    [int]$Carregados = 2,
    [int]$DormirMinutos = 15,
    [switch]$Rede,
    [switch]$SemNavegador,
    [switch]$IncluirGigantes
)
. "$PSScriptRoot\comum.ps1"

$cat = Ler-Catalogo
$estado = Ler-Estado
$exe = Achar-Exe 'llama.cpp' 'llama-server.exe'

# Gera o arquivo de presets a partir do catalogo (so modelos ja baixados).
$ini = New-Object System.Collections.Generic.List[string]
$ini.Add('; Gerado por iniciar-servidor.ps1 a partir de catalogo\modelos.json. Nao edite: rode o script de novo.')
$ini.Add('version = 1')
$ini.Add('')
$ini.Add('[*]')
$ini.Add('fit = on')
# Modelo parado libera a placa de video e a memoria; a proxima pergunta o carrega de novo.
if ($DormirMinutos -gt 0) { $ini.Add("sleep-idle-seconds = $($DormirMinutos * 60)") }
$ini.Add('')
$incluidos = @()
$escondidos = @()
# Modelos maiores que RAM + VRAM leriam do disco a cada palavra e travariam o PC: ficam de fora por padrao.
$memoriaGB = [math]::Round(((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB) + 12)
foreach ($m in @($cat.modelos | Where-Object { $_.status -eq 'baixar' -and $_.motor -eq 'llama.cpp' })) {
    if (-not ($estado.modelos.Contains($m.id) -and $estado.modelos[$m.id].completo)) { continue }
    if (-not $IncluirGigantes -and [double]$m.tamanho_gb -gt ($memoriaGB - 8)) { $escondidos += $m.id; continue }
    $arqs = @($m.arquivos | ForEach-Object { Caminho-Destino $m $_ })
    $modelo = $arqs | Where-Object { (Split-Path $_ -Leaf) -notmatch '^(mmproj|mtp-)' -and $_ -match '\.gguf$' } | Select-Object -First 1
    $mmproj = $arqs | Where-Object { (Split-Path $_ -Leaf) -match '^mmproj' } | Select-Object -First 1
    $mtp = $arqs | Where-Object { (Split-Path $_ -Leaf) -match '^mtp-' -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    $ini.Add("[$($m.id)]")
    $ini.Add("model = $modelo")
    if ($mmproj) { $ini.Add("mmproj = $mmproj") }
    # Cabeca MTP: preve varios tokens de uma vez (medido: Qwen3.8 27B +76%, Gemma 4 26B +21%).
    if ($mtp) { $ini.Add('spec-type = draft-mtp'); $ini.Add("spec-draft-model = $mtp") }
    if ($m.contexto) { $ini.Add("c = $($m.contexto)") }
    # Converte "--embedding --pooling last" em linhas do INI.
    $tokens = @(([string]$m.args) -split '\s+' | Where-Object { $_ })
    for ($i = 0; $i -lt $tokens.Count; $i++) {
        $chave = $tokens[$i].TrimStart('-')
        if ($i + 1 -lt $tokens.Count -and -not $tokens[$i + 1].StartsWith('-')) { $ini.Add("$chave = $($tokens[$i + 1])"); $i++ }
        else { $ini.Add("$chave = true") }
    }
    $ini.Add('')
    $incluidos += $m.id
}
if ($incluidos.Count -eq 0) { throw 'Nenhum modelo de chat baixado ainda. Rode: .\baixar-modelo.ps1 -Id gemma-4-12b' }
$arqIni = Join-Path $PastaCatalogo 'llama-presets.ini'
[IO.File]::WriteAllLines($arqIni, $ini, (New-Object Text.UTF8Encoding $false))

$ip = '127.0.0.1'
if ($Rede) { $ip = '0.0.0.0' }
$url = "http://127.0.0.1:$Porta"
if (-not $SemNavegador) {
    $espera = "for (`$i = 0; `$i -lt 300; `$i++) { try { Invoke-WebRequest -UseBasicParsing '$url/health' -TimeoutSec 2 | Out-Null; Start-Process '$url'; break } catch { Start-Sleep -Seconds 1 } }"
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($espera))
    Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile -EncodedCommand $enc"
}

Titulo 'Servidor de modelos (modo roteador)'
Info "Modelos: $($incluidos -join ', ')"
if ($escondidos.Count -gt 0) { Info "Grandes demais para este PC (use -IncluirGigantes): $($escondidos -join ', ')" }
Info "Chat:    $url"
Info "API:     $url/v1   (campo model = um dos ids acima)"
Info "Ate $Carregados modelo(s) carregados ao mesmo tempo. Para parar: Ctrl+C."
if ($DormirMinutos -gt 0) { Info "Modelo sem uso por $DormirMinutos min sai da memoria sozinho." }
Write-Host ''
Executar-Nativo $exe @('--models-preset', $arqIni, '--models-max', "$Carregados", '--host', $ip, '--port', "$Porta")
