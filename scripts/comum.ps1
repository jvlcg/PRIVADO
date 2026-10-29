# Funcoes compartilhadas pelos scripts do SSD de IAs.
# Os outros scripts carregam este arquivo com:  . "$PSScriptRoot\comum.ps1"
# Compativel com o Windows PowerShell 5.1 (o que vem no Windows).

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

# A raiz e descoberta pela posicao do script: se a letra do SSD mudar, tudo continua funcionando.
$Raiz            = Split-Path -Parent $PSScriptRoot
$PastaModelos    = Join-Path $Raiz 'modelos'
$PastaMotores    = Join-Path $Raiz 'motores'
$PastaCatalogo   = Join-Path $Raiz 'catalogo'
$PastaCache      = Join-Path $Raiz 'cache'
$PastaLogs       = Join-Path $Raiz 'logs'
$ArquivoCatalogo = Join-Path $PastaCatalogo 'modelos.json'
$ArquivoEstado   = Join-Path $PastaCatalogo 'estado.json'
$UserAgent       = 'ssd-ia/1.0'

# O acervo tem dois lugares: 'nucleo' (este SSD) e 'cofre' (outro disco, definido em cofre.raiz no catalogo).
function Raiz-Cofre {
    if ($null -eq $script:RaizCofre) {
        $script:RaizCofre = ''
        $c = Ler-Json $ArquivoCatalogo
        if ($c -and $c.cofre -and $c.cofre.raiz) { $script:RaizCofre = [string]$c.cofre.raiz }
    }
    return $script:RaizCofre
}

function Base-Local($local) {
    if ($local -eq 'cofre') {
        $r = Raiz-Cofre
        if (-not $r) { throw 'Cofre nao configurado no catalogo (campo cofre.raiz).' }
        return $r
    }
    return $Raiz
}

function Caminho-Absoluto($relativo, $local) {
    if ([IO.Path]::IsPathRooted($relativo)) { return $relativo }
    return Join-Path (Base-Local $local) $relativo
}

function ConvertTo-Hashtable($obj) {
    if ($null -eq $obj) { return $null }
    if ($obj -is [System.Collections.IDictionary]) { return $obj }
    if ($obj -is [System.Management.Automation.PSCustomObject]) {
        $h = [ordered]@{}
        foreach ($p in $obj.PSObject.Properties) { $h[$p.Name] = ConvertTo-Hashtable $p.Value }
        return $h
    }
    if ($obj -is [System.Collections.IEnumerable] -and $obj -isnot [string]) {
        return ,([object[]]@($obj | ForEach-Object { ConvertTo-Hashtable $_ }))
    }
    return $obj
}

function Ler-Json($caminho) {
    if (-not (Test-Path -LiteralPath $caminho)) { return $null }
    $txt = [IO.File]::ReadAllText($caminho, [Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($txt)) { return $null }
    return ($txt | ConvertFrom-Json)
}

function Salvar-Json($obj, $caminho) {
    $json = $obj | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($caminho, $json, (New-Object Text.UTF8Encoding $false))
}

function Ler-Catalogo {
    $c = Ler-Json $ArquivoCatalogo
    if (-not $c) { throw "Catalogo nao encontrado: $ArquivoCatalogo" }
    return $c
}

function Ler-Estado {
    $e = ConvertTo-Hashtable (Ler-Json $ArquivoEstado)
    if (-not $e) { $e = [ordered]@{} }
    foreach ($k in 'modelos', 'conhecimento', 'motores', 'observados', 'orgs_visto') {
        if (-not $e.Contains($k) -or $null -eq $e[$k]) { $e[$k] = [ordered]@{} }
    }
    return $e
}

function Salvar-Estado($estado) { Salvar-Json $estado $ArquivoEstado }

# Le, altera e grava o estado com trava: varios downloads podem rodar ao mesmo tempo sem um apagar o outro.
# Uso: $estado = Atualizar-Estado { param($e) $e.modelos['x'] = ... }
function Atualizar-Estado([scriptblock]$alteracao) {
    $trava = New-Object System.Threading.Mutex($false, 'Global\SSD-IA-estado')
    [void]$trava.WaitOne()
    try {
        $e = Ler-Estado
        & $alteracao $e
        Salvar-Estado $e
        return $e
    } finally {
        $trava.ReleaseMutex()
        $trava.Dispose()
    }
}

function Caminho-Relativo($caminho, $local = 'nucleo') {
    $base = Base-Local $local
    if ($caminho.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) {
        return $caminho.Substring($base.Length).TrimStart('\')
    }
    return $caminho
}

function Invoke-Api($url) {
    $headers = @{ 'User-Agent' = $UserAgent }
    if ($env:HF_TOKEN -and $url -like 'https://huggingface.co/*') { $headers['Authorization'] = "Bearer $($env:HF_TOKEN)" }
    if ($env:GITHUB_TOKEN -and $url -like 'https://api.github.com/*') { $headers['Authorization'] = "Bearer $($env:GITHUB_TOKEN)" }
    return Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 60
}

# Le uma URL como texto, mesmo quando o servidor diz que e binario (caso dos .md5 e .sha256 da Kiwix).
function Baixar-Texto($url) {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 60 -UserAgent $UserAgent
    if ($r.Content -is [byte[]]) { return [Text.Encoding]::UTF8.GetString($r.Content) }
    return [string]$r.Content
}

# Arquivos de UMA pasta de um repositorio do Hugging Face (com tamanho e SHA256), guardados em memoria.
# Lista so a pasta do arquivo: em repositorios enormes (ex.: vozes do Piper) a listagem completa vem
# paginada e o arquivo procurado pode nao aparecer na primeira pagina.
$script:CacheArvore = @{}
function Obter-ArquivosPasta($repo, $pasta) {
    $chave = "$repo|$pasta"
    if (-not $script:CacheArvore.ContainsKey($chave)) {
        $url = "https://huggingface.co/api/models/$repo/tree/main"
        if ($pasta) { $url += '/' + (($pasta -split '/' | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/') }
        $t = Invoke-Api $url
        $script:CacheArvore[$chave] = @($t | Where-Object { $_.type -eq 'file' })
    }
    return $script:CacheArvore[$chave]
}

function Obter-InfoArquivo($repo, $caminho) {
    $pasta = ''
    if ($caminho.Contains('/')) { $pasta = $caminho.Substring(0, $caminho.LastIndexOf('/')) }
    $f = Obter-ArquivosPasta $repo $pasta | Where-Object { $_.path -eq $caminho } | Select-Object -First 1
    if (-not $f) { throw "Arquivo '$caminho' nao existe mais em $repo. Rode verificar-atualizacoes.ps1 e ajuste o catalogo." }
    $sha = $null
    if ($f.lfs) { $sha = [string]$f.lfs.oid }
    return [pscustomobject]@{ caminho = $f.path; tamanho = [int64]$f.size; sha256 = $sha }
}

function Obter-InfoRepo($repo) {
    return Invoke-Api "https://huggingface.co/api/models/$repo`?expand[]=sha&expand[]=lastModified&expand[]=gated"
}

function Caminho-Destino($modelo, $arq) {
    $rel = $arq.destino
    if (-not $rel) { $rel = Split-Path $arq.caminho -Leaf }
    $base = Join-Path (Base-Local $modelo.local) 'modelos'
    return Join-Path (Join-Path $base $modelo.pasta) $rel
}

function Espaco-LivreGB($caminho = $Raiz) {
    $letra = [IO.Path]::GetPathRoot($caminho).Substring(0, 1)
    return [math]::Round((Get-PSDrive $letra).Free / 1GB, 1)
}

function Hash-Arquivo($caminho) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $caminho).Hash.ToLower()
}

# Baixa uma URL com retomada. Se a conexao cair ou ficar abaixo de 1 MB/s por 60 s (servidor "travado"),
# reconecta e continua do ponto onde parou, ate 30 vezes. Rodar o script de novo tambem continua.
function Baixar-Url($url, $destino, [switch]$Silencioso, [switch]$ComTokenHF, [int]$Tentativas = 30) {
    $base = @('-L', '--fail', '-C', '-', '-o', $destino, '-A', $UserAgent, '--connect-timeout', '30', '--speed-limit', '1048576', '--speed-time', '60')
    if ($Silencioso) { $base += '-sS' } else { $base += '--progress-bar' }
    if ($ComTokenHF -and $env:HF_TOKEN) { $base += @('-H', "Authorization: Bearer $($env:HF_TOKEN)") }
    # Codigos do curl que valem nova tentativa: rede, tempo esgotado, transferencia parcial, erro HTTP (5xx).
    $transitorios = 6, 7, 18, 22, 28, 35, 52, 55, 56, 92
    for ($tentativa = 1; $tentativa -le $Tentativas; $tentativa++) {
        Executar-Nativo 'curl.exe' ($base + $url)
        if ($LASTEXITCODE -eq 0) { return }
        if ($transitorios -notcontains $LASTEXITCODE) { break }
        Aviso "Conexao lenta ou interrompida (curl $LASTEXITCODE); retomando ($tentativa de $Tentativas)..."
        Start-Sleep -Seconds 5
    }
    throw "Falha no download (curl codigo $LASTEXITCODE): $url"
}

# Roda um programa externo sem que o PowerShell 5.1 trate a saida de progresso (stderr) como erro.
# Quem chama confere $LASTEXITCODE.
function Executar-Nativo($exe, $argumentos) {
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $exe @argumentos } finally { $ErrorActionPreference = $eap }
}

function Versao-CudaDriver {
    try { $txt = (& nvidia-smi 2>$null) -join "`n" } catch { return 0 }
    if ($txt -match 'CUDA (?:UMD )?Version:\s*(\d+)\.(\d+)') { return [int]$Matches[1] }
    return 0
}

# Espelhos da Kiwix (a velocidade varia de 0,3 a 46 MB/s). O hash sempre vem do site oficial.
$EspelhosKiwix = @(
    'https://ftpmirror.your.org/pub/kiwix/',
    'https://ny.mirror.driftle.ss/kiwix/',
    'https://mirrors.dotsrc.org/kiwix/',
    'https://lb.download.kiwix.org/',
    'https://ftp.nluug.nl/pub/kiwix/'
)

# Mede cada espelho baixando 32 MB do proprio arquivo. Devolve todos os que funcionaram, do mais rapido
# ao mais lento, com o site oficial por ultimo: se um espelho derrubar a conexao, tenta-se o proximo.
function Espelhos-Kiwix($caminhoRel) {
    $medidos = @()
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        foreach ($e in $EspelhosKiwix) {
            $r = & curl.exe -s -L -r 0-33554431 -o NUL --max-time 6 -A $UserAgent -w '%{speed_download} %{http_code}' "$e$caminhoRel"
            $p = "$r" -split ' '
            if ($p.Count -ge 2 -and $p[1] -eq '206') { $medidos += [pscustomobject]@{ url = "$e$caminhoRel"; mbps = [math]::Round([double]$p[0] / 1MB, 1) } }
        }
    } finally { $ErrorActionPreference = $eap }
    $lista = @($medidos | Sort-Object mbps -Descending)
    $lista += [pscustomobject]@{ url = "https://download.kiwix.org/$caminhoRel"; mbps = 0 }
    return $lista
}

function Melhor-EspelhoKiwix($caminhoRel) { return (Espelhos-Kiwix $caminhoRel)[0] }

# Versao mais recente de uma biblioteca ZIM no site da Kiwix (os arquivos tem a data no nome: _AAAA-MM.zim;
# uma republicacao no mesmo mes ganha uma letra, como _2026-07a.zim, que vem depois de _2026-07.zim).
$script:CacheListagem = @{}
function Versao-Zim($item) {
    $url = "https://download.kiwix.org/zim/$($item.pasta_kiwix)/"
    if (-not $script:CacheListagem.ContainsKey($url)) {
        $script:CacheListagem[$url] = (Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 60 -UserAgent $UserAgent).Content
    }
    $padrao = '(?<=href=")' + [regex]::Escape($item.prefixo) + '_(\d{4}-\d{2}[a-z]?)\.zim(?=")'
    $ms = @([regex]::Matches($script:CacheListagem[$url], $padrao))
    if ($ms.Count -eq 0) { return $null }
    $ultimo = $ms | Sort-Object { $_.Groups[1].Value } | Select-Object -Last 1
    return [pscustomobject]@{ arquivo = $ultimo.Value; versao = $ultimo.Groups[1].Value; url = "$url$($ultimo.Value)" }
}

# Escolhe o arquivo do motor conforme a placa: CUDA 13, CUDA 12 ou sem NVIDIA.
function Padroes-Motor($def) {
    $cuda = Versao-CudaDriver
    $principal = $def.asset
    $extras = @($def.extras | Where-Object { $_ })
    if ($principal -match '\{cuda\}') {
        $tag = $null
        if ($cuda -ge 13) { $tag = '13' } elseif ($cuda -eq 12) { $tag = '12' }
        if ($tag) {
            $principal = $principal.Replace('{cuda}', $tag)
            $extras = @($extras | ForEach-Object { $_.Replace('{cuda}', $tag) })
        } else {
            $principal = $def.asset_sem_cuda
            $extras = @()
        }
    } elseif ($cuda -eq 0 -and $def.asset_sem_cuda) {
        $principal = $def.asset_sem_cuda
    }
    return [pscustomobject]@{ principal = $principal; extras = $extras }
}

# Versao mais recente no GitHub que ja tem o arquivo para Windows publicado.
function Obter-ReleaseComAsset($repo, $padrao) {
    $rels = Invoke-Api "https://api.github.com/repos/$repo/releases?per_page=15"
    foreach ($r in $rels) {
        if ($r.draft) { continue }
        if (@($r.assets | Where-Object { $_.name -match $padrao }).Count -gt 0) { return $r }
    }
    return $null
}

# Pasta da versao instalada de um motor (lida de motores\<id>\atual.txt).
function Pasta-Motor($id) {
    $arq = Join-Path (Join-Path $PastaMotores $id) 'atual.txt'
    if (-not (Test-Path -LiteralPath $arq)) { return $null }
    $versao = (Get-Content -LiteralPath $arq -TotalCount 1).Trim()
    return Join-Path (Join-Path $PastaMotores $id) $versao
}

function Achar-Exe($id, $nomeExe) {
    $pasta = Pasta-Motor $id
    if (-not $pasta) { throw "Motor '$id' nao instalado. Rode: .\instalar-motores.ps1 -Motor $id" }
    $exe = Get-ChildItem -LiteralPath $pasta -Recurse -Filter $nomeExe -File | Select-Object -First 1
    if (-not $exe) { throw "Nao achei $nomeExe em $pasta" }
    return $exe.FullName
}

# Configura o uv para guardar Python, pacotes e cache dentro do SSD. Devolve o caminho do uv.exe.
function Preparar-Uv {
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $PastaMotores 'python'
    $env:UV_CACHE_DIR          = Join-Path $PastaCache 'uv'
    $env:UV_TOOL_DIR           = Join-Path $PastaMotores 'uv-tools'
    $env:UV_PYTHON_PREFERENCE  = 'only-managed'
    $env:UV_PYTHON_BIN_DIR     = Join-Path $PastaMotores 'python\bin'
    $env:UV_PYTHON_INSTALL_BIN = '0'
    $env:HF_HOME               = Join-Path $PastaCache 'hf'
    return (Achar-Exe 'uv' 'uv.exe')
}

# Pede ao Windows para nao suspender por inatividade enquanto este processo roda (downloads longos).
# Vale so para este processo e acaba sozinho quando ele termina; nao impede suspensao manual.
function Manter-Acordado {
    try {
        if (-not ('SsdIa.Energia' -as [type])) {
            Add-Type -Namespace SsdIa -Name Energia -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
        }
        # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x1)
        [void][SsdIa.Energia]::SetThreadExecutionState([uint32]2147483649)
    } catch {}
}

# Chave de acesso dos servidores de modelos: sem ela, um site aberto no navegador poderia mandar
# o PC rodar modelos escondido. Cada PC gera a sua na primeira vez; o arquivo fica fora do git.
$ArquivoChave = Join-Path $PastaCatalogo 'chave-api.txt'
function Chave-Api {
    if (-not (Test-Path -LiteralPath $ArquivoChave)) {
        $bytes = New-Object byte[] 18
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $nova = 'cofre-' + ([Convert]::ToBase64String($bytes) -replace '[+/=]', '')
        [IO.File]::WriteAllText($ArquivoChave, $nova, (New-Object Text.UTF8Encoding $false))
    }
    return (Get-Content -LiteralPath $ArquivoChave -TotalCount 1).Trim()
}

# Programas abertos a partir do cofre (pastas motores e cache, no SSD e no HD): servidores, ComfyUI, conselho.
function Processos-Cofre {
    $pastas = @((Join-Path $Raiz 'motores'), (Join-Path $Raiz 'cache'))
    $rc = Raiz-Cofre
    if ($rc) { $pastas += (Join-Path $rc 'motores') }
    $pastas = @($pastas | ForEach-Object { $_.TrimEnd('\') + '\' })
    return @(Get-Process | Where-Object {
        $exe = $_.Path
        $exe -and $_.Id -ne $PID -and @($pastas | Where-Object { $exe.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
    })
}

# Notificacao do Windows (canto da tela). Falha em silencio se o sistema nao permitir.
function Notificar($titulo, $texto) {
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $nos = $xml.GetElementsByTagName('text')
        $nos.Item(0).AppendChild($xml.CreateTextNode($titulo)) | Out-Null
        $nos.Item(1).AppendChild($xml.CreateTextNode($texto)) | Out-Null
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
    } catch {}
}

function Titulo($texto) { Write-Host ''; Write-Host "== $texto ==" -ForegroundColor Cyan }
function Ok($texto)     { Write-Host "  [ok] $texto" -ForegroundColor Green }
function Aviso($texto)  { Write-Host "  [!]  $texto" -ForegroundColor Yellow }
function Info($texto)   { Write-Host "       $texto" }
