<#
.SYNOPSIS
  Baixa e instala os motores dentro do SSD, sem instalar nada no Windows.
  Cada versao fica em motores\<motor>\<versao>\ e motores\<motor>\atual.txt diz qual usar.
  Rodar de novo instala a versao mais nova ao lado da antiga (a antiga fica de reserva).
  Motores marcados com "guardar" no catalogo (instaladores para Linux, Mac, celular) so sao guardados.
.EXAMPLE
  .\instalar-motores.ps1                              # so o llama.cpp
  .\instalar-motores.ps1 -Motor llama.cpp,whisper.cpp
  .\instalar-motores.ps1 -Todos                       # todos os motores do catalogo
#>
param([string[]]$Motor = @('llama.cpp'), [switch]$Todos, [switch]$ManterInstaladores)
. "$PSScriptRoot\comum.ps1"

$cat = Ler-Catalogo
$pastaDl = Join-Path $PastaCache 'downloads'
New-Item -ItemType Directory -Force -Path $pastaDl | Out-Null
if ($Todos) { $Motor = @($cat.motores | ForEach-Object { $_.id }) }

# Faz o ComfyUI ler os modelos do SSD (modelos\imagem) e do cofre (modelos\comfyui), sem copiar nada.
function Configurar-ComfyUI($pastaVer) {
    $comfy = Get-ChildItem -LiteralPath $pastaVer -Directory -Recurse -Depth 2 -Filter 'ComfyUI' |
        Where-Object { Test-Path (Join-Path $_.FullName 'main.py') } | Select-Object -First 1
    if (-not $comfy) { Aviso 'Nao achei a pasta do ComfyUI para configurar os modelos.'; return }
    $subs = 'checkpoints', 'diffusion_models', 'text_encoders', 'clip_vision', 'vae', 'loras', 'upscale_models', 'controlnet'
    $bases = [ordered]@{ ssd_ia = (Join-Path $PastaModelos 'imagem') }
    $rc = Raiz-Cofre
    if ($rc -and (Test-Path ([IO.Path]::GetPathRoot($rc)))) { $bases['cofre_ia'] = Join-Path $rc 'modelos\comfyui' }
    $linhas = @(
        '# Gerado por instalar-motores.ps1: o ComfyUI le os modelos direto do acervo (SSD e cofre).',
        '# Se a letra de um disco mudar, rode instalar-motores.ps1 -Motor comfyui de novo.'
    )
    foreach ($nome in $bases.Keys) {
        foreach ($s in $subs) { New-Item -ItemType Directory -Force -Path (Join-Path $bases[$nome] $s) | Out-Null }
        $linhas += "${nome}:"
        $linhas += "    base_path: $($bases[$nome].Replace('\', '/'))/"
        $linhas += '    clip: text_encoders/'
        foreach ($s in $subs) { $linhas += "    ${s}: $s/" }
    }
    [IO.File]::WriteAllLines((Join-Path $comfy.FullName 'extra_model_paths.yaml'), $linhas, (New-Object Text.UTF8Encoding $false))
    Ok "ComfyUI configurado para ler: $($bases.Values -join ' e ')"
}

# Para motores publicados fora do GitHub (Kiwix): le a pagina de arquivos e pega a maior versao.
function Obter-ReleaseListagem($def, $padrao) {
    $html = (Invoke-WebRequest -UseBasicParsing -Uri $def.listagem -TimeoutSec 60 -UserAgent $UserAgent).Content
    $nomes = @([regex]::Matches($html, 'href="([^"/?]+)"') | ForEach-Object { $_.Groups[1].Value } | Where-Object { $_ -match $padrao } | Select-Object -Unique)
    if ($nomes.Count -eq 0) { return $null }
    # A versao e o trecho final do nome: ..._2.5.1.zip, ...-3.8.1-2.zip, ..._2.0.tar.gz
    $padraoVer = '(\d+(?:\.\d+)*)(?:-(\d+))?\.(?:zip|tar\.gz|7z)$'
    $ultimo = $nomes | Sort-Object {
        $v = [regex]::Match($_, $padraoVer)
        $n = @($v.Groups[1].Value -split '\.' | ForEach-Object { [int]$_ })
        while ($n.Count -lt 3) { $n += 0 }
        $rev = 0
        if ($v.Groups[2].Success) { $rev = [int]$v.Groups[2].Value }
        [version]('{0}.{1}.{2}.{3}' -f $n[0], $n[1], $n[2], $rev)
    } | Select-Object -Last 1
    $mv = [regex]::Match($ultimo, $padraoVer)
    $ver = $mv.Groups[1].Value
    if ($mv.Groups[2].Success) { $ver = "$ver-$($mv.Groups[2].Value)" }
    $rel = ($def.listagem -replace '^https://download\.kiwix\.org/', '') + $ultimo
    $url = (Melhor-EspelhoKiwix $rel).url
    $asset = [pscustomobject]@{ name = $ultimo; size = 0; browser_download_url = $url; digest = $null; md5 = "$($def.listagem)$ultimo.md5" }
    return [pscustomobject]@{ tag_name = $ver; published_at = ''; assets = @($asset); zipball_url = $null }
}

foreach ($id in $Motor) {
    $def = $cat.motores | Where-Object { $_.id -eq $id } | Select-Object -First 1
    if (-not $def) { Aviso "Motor desconhecido: $id (opcoes: $($cat.motores.id -join ', '))"; continue }
    Titulo $def.nome
    $pad = Padroes-Motor $def
    if ($def.listagem) { $rel = Obter-ReleaseListagem $def $pad.principal } else { $rel = Obter-ReleaseComAsset $def.github $pad.principal }
    if (-not $rel) { Aviso 'Nenhuma versao encontrada para este sistema.'; continue }

    $tag = $rel.tag_name
    $pastaBase = Join-Path $PastaMotores $id
    $pastaVer = Join-Path $pastaBase $tag
    if (Test-Path -LiteralPath $pastaVer) {
        Ok "$tag ja instalado"
    } else {
        $assets = @($rel.assets | Where-Object { $_.name -match $pad.principal })
        foreach ($e in $pad.extras) { $assets += @($rel.assets | Where-Object { $_.name -match $e }) }
        $total = ($assets | Measure-Object -Property size -Sum).Sum
        Info ("Versao {0}: {1} arquivo(s), {2:N0} MB" -f $tag, $assets.Count, ($total / 1MB))
        if (($total * 3) / 1GB + 2 -gt (Espaco-LivreGB)) { throw 'Espaco insuficiente no SSD.' }

        $tmp = "$pastaVer.tmp"
        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        foreach ($as in $assets) {
            $arq = Join-Path $pastaDl $as.name
            if (-not ((Test-Path -LiteralPath $arq) -and $as.size -gt 0 -and (Get-Item -LiteralPath $arq).Length -eq $as.size)) {
                Info "Baixando $($as.name)"
                Baixar-Url $as.browser_download_url $arq -Silencioso
            }
            if ($as.digest -and ([string]$as.digest).StartsWith('sha256:')) {
                if ((Hash-Arquivo $arq) -ne ([string]$as.digest).Substring(7).ToLower()) {
                    Remove-Item -LiteralPath $arq -Force
                    throw "Hash diferente em $($as.name); arquivo descartado, rode de novo."
                }
                Ok "$($as.name) conferido (SHA256)"
            } elseif ($as.md5) {
                try {
                    $md5 = ((Baixar-Texto $as.md5).Trim() -split '\s+')[0].ToLower()
                    if ((Get-FileHash -Algorithm MD5 -LiteralPath $arq).Hash.ToLower() -ne $md5) { Remove-Item -LiteralPath $arq -Force; throw "MD5 diferente em $($as.name)" }
                    Ok "$($as.name) conferido (MD5)"
                } catch [System.Net.WebException] { Aviso "Sem hash publicado para $($as.name)" }
            }
            if ($def.guardar) {
                Move-Item -Force -LiteralPath $arq -Destination (Join-Path $tmp $as.name)
            } else {
                Info "Extraindo $($as.name)"
                Executar-Nativo 'tar.exe' @('-xf', $arq, '-C', $tmp)
                if ($LASTEXITCODE -ne 0) { throw "Falha ao extrair $($as.name)" }
                if (-not $ManterInstaladores) { Remove-Item -LiteralPath $arq -Force }
            }
        }
        if ($def.codigo_fonte -and $rel.zipball_url) {
            Info 'Baixando o codigo-fonte (para compilar em qualquer maquina)'
            Baixar-Url $rel.zipball_url (Join-Path $tmp "$id-$tag-codigo-fonte.zip") -Silencioso
        }
        Rename-Item -LiteralPath $tmp -NewName $tag
        Ok "Instalado em $(Caminho-Relativo $pastaVer)"
    }

    [IO.File]::WriteAllText((Join-Path $pastaBase 'atual.txt'), $tag)
    $registro = [ordered]@{ versao = $tag; publicado = [string]$rel.published_at; instalado_em = (Get-Date -Format s) }
    $null = Atualizar-Estado { param($e) $e.motores[$id] = $registro }
    if ($id -eq 'comfyui') { Configurar-ComfyUI $pastaVer }
}
