<#
.SYNOPSIS
  Move modelos ja baixados entre o SSD (nucleo) e o cofre, sem baixar de novo.
  O lugar certo vem do campo "local" de cada modelo no catalogo: mude la e rode este script.
  Cada arquivo e copiado, conferido pelo SHA256 e so entao apagado da origem.
.EXAMPLE
  .\mover-modelo.ps1                       # arruma tudo que esta fora do lugar
  .\mover-modelo.ps1 -Id devstral-small-2
#>
param([string[]]$Id)
. "$PSScriptRoot\comum.ps1"

$cat = Ler-Catalogo
$estado = Ler-Estado
$movidos = 0

foreach ($m in @($cat.modelos | Where-Object { $_.status -eq 'baixar' -and $estado.modelos.Contains($_.id) })) {
    if ($Id -and $Id -notcontains $m.id) { continue }
    $reg = $estado.modelos[$m.id]
    $atual = 'nucleo'
    if ($reg.local) { $atual = $reg.local }
    $quer = 'nucleo'
    if ($m.local) { $quer = $m.local }
    if ($atual -eq $quer) { continue }

    Titulo "$($m.id): $atual -> $quer"
    $novos = [ordered]@{}
    $pastasOrigem = @()
    foreach ($a in $m.arquivos) {
        $f = $reg.arquivos[$a.caminho]
        if (-not $f) { continue }
        $origem = Caminho-Absoluto $f.destino $atual
        $destino = Caminho-Destino $m $a
        if (-not (Test-Path -LiteralPath $origem)) { Aviso "Nao achei $origem"; continue }
        if (([int64]$f.tamanho / 1GB) + 2 -gt (Espaco-LivreGB $destino)) { throw "Sem espaco em $([IO.Path]::GetPathRoot($destino))" }
        New-Item -ItemType Directory -Force -Path (Split-Path $destino -Parent) | Out-Null
        Info ("Copiando {0} ({1:N2} GB)" -f (Split-Path $origem -Leaf), ([int64]$f.tamanho / 1GB))
        Copy-Item -LiteralPath $origem -Destination $destino -Force
        if ((Hash-Arquivo $destino) -ne $f.sha256) { Remove-Item -LiteralPath $destino -Force; throw "Copia de $origem saiu diferente; a origem foi mantida." }
        Remove-Item -LiteralPath $origem -Force
        $pastasOrigem += (Split-Path $origem -Parent)
        $novo = [ordered]@{}
        foreach ($k in $f.Keys) { $novo[$k] = $f[$k] }
        $novo.destino = Caminho-Relativo $destino $quer
        $novos[$a.caminho] = $novo
        Ok "$(Split-Path $destino -Leaf) movido e conferido"
    }
    $estado = Atualizar-Estado {
        param($e)
        $e.modelos[$m.id].local = $quer
        foreach ($k in $novos.Keys) { $e.modelos[$m.id].arquivos[$k] = $novos[$k] }
    }
    foreach ($p in ($pastasOrigem | Select-Object -Unique)) {
        if ((Test-Path -LiteralPath $p) -and -not (Get-ChildItem -LiteralPath $p -Force)) { Remove-Item -LiteralPath $p }
    }
    $movidos++
}
if ($movidos -eq 0) { Ok 'Tudo ja esta no lugar definido no catalogo.' }
