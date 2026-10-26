<#
.SYNOPSIS
  Baixa modelos do catalogo, com retomada e conferencia de SHA256.
  Cada modelo vai para o seu lugar: 'nucleo' (este SSD) ou 'cofre' (o disco de arquivo do catalogo).
.EXAMPLE
  .\baixar-modelo.ps1 -Listar
  .\baixar-modelo.ps1 -Id gemma-4-12b
  .\baixar-modelo.ps1 -Id gemma-4-12b,qwen3-embedding-0.6b
  .\baixar-modelo.ps1 -Prioridade 2                  # tudo ate prioridade 2 que mora no SSD
  .\baixar-modelo.ps1 -Prioridade 2 -Local cofre     # tudo ate prioridade 2 que mora no cofre
  .\baixar-modelo.ps1 -Prioridade 3 -Local todos
.NOTES
  Modelos com licenca que exige login: crie um token em https://huggingface.co/settings/tokens
  e rode antes:  $env:HF_TOKEN = 'hf_...'
#>
param(
    [string[]]$Id,
    [int]$Prioridade = 0,
    [ValidateSet('nucleo', 'cofre', 'todos')][string]$Local = 'nucleo',
    [switch]$Listar,
    [switch]$Silencioso
)
. "$PSScriptRoot\comum.ps1"

$cat = Ler-Catalogo
$estado = Ler-Estado
$baixaveis = @($cat.modelos | Where-Object { $_.status -eq 'baixar' })

function Local-De($m) { if ($m.local) { return $m.local } return 'nucleo' }
function Esta-Completo($id) { return ($estado.modelos.Contains($id) -and $estado.modelos[$id].completo) }

if ($Listar -or (-not $Id -and $Prioridade -eq 0)) {
    $baixaveis | Sort-Object { Local-De $_ }, prioridade, tipo, id | ForEach-Object {
        $b = '-'
        if (Esta-Completo $_.id) { $b = 'sim' }
        [pscustomobject]@{ Id = $_.id; Tipo = $_.tipo; GB = $_.tamanho_gb; Prior = $_.prioridade; Local = (Local-De $_); Baixado = $b; Motor = $_.motor }
    } | Format-Table -AutoSize | Out-String -Width 160 | Write-Host
    Write-Host ("Livre no SSD: {0} GB" -f (Espaco-LivreGB))
    $rc = Raiz-Cofre
    if ($rc -and (Test-Path ([IO.Path]::GetPathRoot($rc)))) { Write-Host ("Livre no cofre ({0}): {1} GB" -f $rc, (Espaco-LivreGB $rc)) }
    Write-Host 'Uso: .\baixar-modelo.ps1 -Id <id>    ou    .\baixar-modelo.ps1 -Prioridade 2 [-Local nucleo|cofre|todos]'
    return
}

if ($Id) {
    $desconhecidos = @($Id | Where-Object { $baixaveis.id -notcontains $_ })
    if ($desconhecidos.Count -gt 0) { throw "Id(s) fora do catalogo: $($desconhecidos -join ', '). Veja a lista com -Listar." }
    $sel = @($baixaveis | Where-Object { $Id -contains $_.id })
} else {
    $sel = @($baixaveis | Where-Object { $_.prioridade -le $Prioridade -and ($Local -eq 'todos' -or (Local-De $_) -eq $Local) } | Sort-Object prioridade)
}

# 1. Planejamento: o que falta baixar e quanto espaco precisa em cada disco.
Titulo 'Planejando'
$plano = @()
foreach ($m in $sel) {
    $loc = Local-De $m
    foreach ($a in $m.arquivos) {
        $info = Obter-InfoArquivo $m.repo $a.caminho
        $dest = Caminho-Destino $m $a
        $reg = $null
        if ($estado.modelos.Contains($m.id)) { $reg = $estado.modelos[$m.id].arquivos[$a.caminho] }
        # Arquivos pequenos (fora do LFS) nao tem SHA256 publicado: basta o tamanho bater.
        $pronto = ($reg -and (Test-Path -LiteralPath $dest) -and (Get-Item -LiteralPath $dest).Length -eq $info.tamanho -and
                   (-not $info.sha256 -or $reg.sha256 -eq $info.sha256))
        $plano += [pscustomobject]@{ modelo = $m; local = $loc; arq = $a; info = $info; dest = $dest; pronto = $pronto }
    }
}
$falta = @($plano | Where-Object { -not $_.pronto })
Info ("{0} arquivo(s) para baixar." -f $falta.Count)
if ($falta.Count -eq 0) { Ok 'Tudo ja esta baixado e conferido.'; return }
foreach ($grupo in ($falta | Group-Object { [IO.Path]::GetPathRoot($_.dest) })) {
    $gb = [math]::Round((($grupo.Group | ForEach-Object { $_.info.tamanho } | Measure-Object -Sum).Sum) / 1GB, 2)
    $livre = Espaco-LivreGB $grupo.Name
    Info ("Disco {0}  precisa {1} GB, livre {2} GB" -f $grupo.Name, $gb, $livre)
    if ($gb + 5 -gt $livre) { throw "Espaco insuficiente em $($grupo.Name): precisa de $gb GB + 5 GB de folga." }
}

# 2. Download, conferencia e registro.
$repoInfo = @{}
foreach ($p in $plano) {
    $m = $p.modelo
    if ($p.pronto) { Ok "$($m.id): $(Split-Path $p.dest -Leaf) ja conferido"; continue }

    Titulo "$($m.nome)  ->  $($p.dest)"
    New-Item -ItemType Directory -Force -Path (Split-Path $p.dest -Parent) | Out-Null
    $parte = "$($p.dest).part"

    $jaTemArquivo = (Test-Path -LiteralPath $p.dest) -and (Get-Item -LiteralPath $p.dest).Length -eq $p.info.tamanho
    if ($jaTemArquivo) {
        Info 'Arquivo ja existe com o tamanho certo; conferindo o hash.'
        $alvo = $p.dest
    } else {
        $parteCompleta = (Test-Path -LiteralPath $parte) -and (Get-Item -LiteralPath $parte).Length -eq $p.info.tamanho
        if (-not $parteCompleta) {
            $url = "https://huggingface.co/$($m.repo)/resolve/main/$($p.arq.caminho)"
            Info ("{0:N2} GB de {1}" -f ($p.info.tamanho / 1GB), $m.repo)
            Baixar-Url $url $parte -Silencioso:$Silencioso -ComTokenHF
        }
        $alvo = $parte
    }

    Info 'Conferindo SHA256...'
    $hash = Hash-Arquivo $alvo
    if ($p.info.sha256 -and $hash -ne $p.info.sha256) {
        if ($alvo -eq $parte) { Remove-Item -LiteralPath $parte -Force }
        Aviso 'Hash diferente do Hugging Face. Download descartado; rode de novo para baixar outra vez.'
        continue
    }
    if ($alvo -eq $parte) { Move-Item -Force -LiteralPath $parte -Destination $p.dest }

    if (-not $repoInfo.ContainsKey($m.repo)) { $repoInfo[$m.repo] = Obter-InfoRepo $m.repo }
    $registro = [ordered]@{
        destino    = Caminho-Relativo $p.dest $p.local
        tamanho    = $p.info.tamanho
        sha256     = $hash
        baixado_em = (Get-Date -Format s)
    }
    $estado = Atualizar-Estado {
        param($e)
        if (-not $e.modelos.Contains($m.id)) { $e.modelos[$m.id] = [ordered]@{ completo = $false; repo = $m.repo; arquivos = [ordered]@{} } }
        $r = $e.modelos[$m.id]
        $r.local = $p.local
        $r.repo_sha = $repoInfo[$m.repo].sha
        $r.repo_modificado = [string]$repoInfo[$m.repo].lastModified
        $r.arquivos[$p.arq.caminho] = $registro
        $r.completo = (@($m.arquivos | Where-Object { -not $r.arquivos.Contains($_.caminho) }).Count -eq 0)
    }
    Ok "$(Split-Path $p.dest -Leaf) baixado e conferido"
}

Titulo 'Resumo'
foreach ($m in $sel) {
    if (Esta-Completo $m.id) { Ok "$($m.id) completo" } else { Aviso "$($m.id) incompleto; rode o comando de novo" }
}
Info ("Livre no SSD agora: {0} GB" -f (Espaco-LivreGB))
