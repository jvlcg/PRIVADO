<#
.SYNOPSIS
  Baixa as bibliotecas offline (Wikipedia, WikiMed, iFixit, livros, foruns) no formato ZIM do Kiwix.
  Sempre pega a versao mais nova publicada e confere o SHA256 da propria Kiwix.
  Quando sai versao nova, rodar de novo baixa a nova e so depois apaga a antiga.
  Para ler: iniciar-biblioteca.ps1 (navegador) ou o Kiwix Desktop.
.EXAMPLE
  .\baixar-conhecimento.ps1 -Listar
  .\baixar-conhecimento.ps1 -Id wikipedia-pt,wikimed
  .\baixar-conhecimento.ps1 -Local nucleo       # tudo que mora no SSD
  .\baixar-conhecimento.ps1 -Local cofre        # tudo que mora no cofre
.NOTES
  Bibliotecas com "status": "observar" no catalogo (as gigantes) ficam fora do -Local e da
  sincronizacao; baixe pelo -Id quando quiser.
#>
param(
    [string[]]$Id,
    [ValidateSet('nucleo', 'cofre', 'todos')][string]$Local,
    [switch]$Listar,
    [switch]$Silencioso
)
. "$PSScriptRoot\comum.ps1"

$cat = Ler-Catalogo
$estado = Ler-Estado
$itens = @($cat.conhecimento)

function Local-De($i) { if ($i.local) { return $i.local } return 'nucleo' }

if ($Listar -or (-not $Id -and -not $Local)) {
    $itens | Sort-Object { Local-De $_ }, id | ForEach-Object {
        $v = '-'
        if ($estado.conhecimento.Contains($_.id)) { $v = $estado.conhecimento[$_.id].versao }
        $s = 'baixar'
        if ($_.status) { $s = $_.status }
        [pscustomobject]@{ Id = $_.id; GB = $_.tamanho_gb; Local = (Local-De $_); Status = $s; Versao = $v; Nome = $_.nome }
    } | Format-Table -AutoSize | Out-String -Width 160 | Write-Host
    Write-Host 'Uso: .\baixar-conhecimento.ps1 -Id <id>   ou   -Local nucleo|cofre|todos'
    return
}

if ($Id) {
    $desconhecidos = @($Id | Where-Object { $itens.id -notcontains $_ })
    if ($desconhecidos.Count -gt 0) { throw "Id(s) fora do catalogo: $($desconhecidos -join ', ')" }
    $sel = @($itens | Where-Object { $Id -contains $_.id })
} else {
    $sel = @($itens | Where-Object { ($Local -eq 'todos' -or (Local-De $_) -eq $Local) -and $_.status -ne 'observar' })
    $obs = @($itens | Where-Object { ($Local -eq 'todos' -or (Local-De $_) -eq $Local) -and $_.status -eq 'observar' })
    if ($obs.Count -gt 0) { Info "Em observacao (baixe com -Id quando quiser): $(($obs | ForEach-Object { "$($_.id) ($($_.tamanho_gb) GB)" }) -join ', ')" }
}

Manter-Acordado
foreach ($item in $sel) {
    $loc = Local-De $item
    Titulo $item.nome
    $ultima = Versao-Zim $item
    if (-not $ultima) { Aviso "Nenhum arquivo $($item.prefixo) encontrado na Kiwix."; continue }
    $pasta = Join-Path (Base-Local $loc) 'conhecimento'
    New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    $dest = Join-Path $pasta $ultima.arquivo
    $reg = $null
    if ($estado.conhecimento.Contains($item.id)) { $reg = $estado.conhecimento[$item.id] }
    if ($reg -and $reg.arquivo -eq $ultima.arquivo -and (Test-Path -LiteralPath $dest)) { Ok "$($ultima.arquivo) ja baixado e conferido"; continue }

    if ($item.tamanho_gb * 1.05 + 5 -gt (Espaco-LivreGB $pasta)) { Aviso "Sem espaco em $pasta para $($item.tamanho_gb) GB."; continue }
    $esperado = ((Baixar-Texto "$($ultima.url).sha256").Trim() -split '\s+')[0].ToLower()
    $parte = "$dest.part"
    # Tenta os espelhos do mais rapido ao mais lento; o .part e o mesmo, entao cada um continua de onde o outro parou.
    $baixou = $false
    foreach ($espelho in (Espelhos-Kiwix "zim/$($item.pasta_kiwix)/$($ultima.arquivo)")) {
        Info ("Versao {0}, cerca de {1} GB, pelo espelho {2} ({3} MB/s)" -f $ultima.versao, $item.tamanho_gb, ([uri]$espelho.url).Host, $espelho.mbps)
        try {
            Baixar-Url $espelho.url $parte -Silencioso:$Silencioso -Tentativas 5
            $baixou = $true
            break
        } catch {
            Aviso "Espelho $(([uri]$espelho.url).Host) falhou: $($_.Exception.Message). Tentando o proximo."
        }
    }
    if (-not $baixou) { Aviso "Nenhum espelho completou $($ultima.arquivo); o que ja veio fica guardado para a proxima vez."; continue }
    Info 'Conferindo SHA256...'
    $hash = Hash-Arquivo $parte
    if ($hash -ne $esperado) { Remove-Item -LiteralPath $parte -Force; Aviso 'Hash diferente do publicado pela Kiwix; download descartado.'; continue }
    Move-Item -Force -LiteralPath $parte -Destination $dest
    $tamanho = (Get-Item -LiteralPath $dest).Length

    # A versao antiga so sai depois que a nova foi conferida.
    if ($reg -and $reg.arquivo -ne $ultima.arquivo) {
        $antigo = Caminho-Absoluto $reg.destino (Local-De $reg)
        if (Test-Path -LiteralPath $antigo) { Remove-Item -LiteralPath $antigo -Force; Info "Versao antiga removida: $($reg.arquivo)" }
    }
    $registro = [ordered]@{
        arquivo = $ultima.arquivo; versao = $ultima.versao; local = $loc
        destino = Caminho-Relativo $dest $loc; tamanho = $tamanho; sha256 = $hash; baixado_em = (Get-Date -Format s)
    }
    $estado = Atualizar-Estado { param($e) $e.conhecimento[$item.id] = $registro }
    Ok ("{0} baixado e conferido ({1:N2} GB)" -f $ultima.arquivo, ($tamanho / 1GB))
}
