<#
.SYNOPSIS
  Mostra o estado do acervo: espaco nos dois discos, tamanho de cada pasta, modelos e
  bibliotecas baixados, motores instalados, a ultima verificacao de novidades e o que do
  cofre esta aberto agora (gastando energia).
#>
. "$PSScriptRoot\comum.ps1"

$cat = Ler-Catalogo
$estado = Ler-Estado

function Tamanho-Pasta($p) {
    $s = (Get-ChildItem -LiteralPath $p -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if (-not $s) { $s = 0 }
    return $s / 1GB
}

$lugares = [ordered]@{ 'SSD (nucleo)' = $Raiz }
$rc = Raiz-Cofre
if ($rc -and (Test-Path -LiteralPath $rc)) { $lugares['Cofre'] = $rc }
foreach ($nome in $lugares.Keys) {
    $base = $lugares[$nome]
    $d = Get-PSDrive ([IO.Path]::GetPathRoot($base).Substring(0, 1))
    Titulo "$nome  $base"
    Info ("Disco: usado {0:N1} GB | livre {1:N1} GB | total {2:N1} GB" -f ($d.Used / 1GB), ($d.Free / 1GB), (($d.Used + $d.Free) / 1GB))
    $subs = @()
    foreach ($s in 'modelos', 'conhecimento') {
        $p = Join-Path $base $s
        if (Test-Path -LiteralPath $p) { $subs += @(Get-ChildItem -LiteralPath $p -Directory | ForEach-Object { "$s\$($_.Name)" }) }
    }
    $subs += 'conhecimento', 'motores', 'dev', 'linux', 'cache', 'espelho-ssd'
    foreach ($s in ($subs | Select-Object -Unique)) {
        $p = Join-Path $base $s
        if (-not (Test-Path -LiteralPath $p)) { continue }
        if ($s -eq 'conhecimento' -and (Get-ChildItem -LiteralPath $p -Directory -ErrorAction SilentlyContinue)) { continue }
        Info ("{0,-26} {1,9:N2} GB" -f $s, (Tamanho-Pasta $p))
    }
}

Titulo 'Modelos'
$acervo = @($cat.modelos | Where-Object { $_.status -eq 'baixar' })
$prontos = @($acervo | Where-Object { $estado.modelos.Contains($_.id) -and $estado.modelos[$_.id].completo })
$obs = @($cat.modelos | Where-Object { $_.status -eq 'observar' })
Info "$($prontos.Count) de $($acervo.Count) modelos baixados; $($obs.Count) em observacao."
foreach ($x in ($prontos | Sort-Object tipo, id)) {
    $l = 'nucleo'
    if ($estado.modelos[$x.id].local) { $l = $estado.modelos[$x.id].local }
    Ok ("{0,-24} {1,-10} {2,8} GB  [{3}]" -f $x.id, $x.tipo, $x.tamanho_gb, $l)
}

Titulo 'Bibliotecas offline'
$libs = @($cat.conhecimento)
$libsOk = @($libs | Where-Object { $estado.conhecimento.Contains($_.id) })
Info "$($libsOk.Count) de $($libs.Count) bibliotecas baixadas."
foreach ($x in $libsOk) { $r = $estado.conhecimento[$x.id]; Ok ("{0,-20} {1}  [{2}]" -f $x.id, $r.versao, $r.local) }

Titulo 'Motores'
foreach ($def in $cat.motores) {
    $v = 'nao instalado'
    if ($estado.motores.Contains($def.id)) { $v = $estado.motores[$def.id].versao }
    Info ("{0,-26} {1}" -f $def.id, $v)
}

Titulo 'Ultima verificacao de novidades'
$u = $estado['ultima_verificacao']
if (-not $u) { $u = 'nunca (rode verificar-atualizacoes.ps1)' }
Info $u

Titulo 'Aberto agora'
$abertos = @(Processos-Cofre)
if ($abertos.Count -eq 0) { Info 'Nada do cofre aberto.' }
else {
    foreach ($g in ($abertos | Group-Object ProcessName)) {
        Info ("{0,-20} {1} processo(s), {2:N1} GB de RAM" -f $g.Name, $g.Count, (($g.Group | Measure-Object WorkingSet64 -Sum).Sum / 1GB))
    }
    Info 'Para fechar tudo e liberar a placa de video: menu, opcao 15.'
}
try {
    $gpu = (& nvidia-smi --query-gpu=memory.used,power.draw --format=csv,noheader) | Select-Object -First 1
    Info "Placa de video: $gpu (memoria usada, consumo)"
} catch {}
