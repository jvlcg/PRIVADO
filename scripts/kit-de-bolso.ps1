<#
  Kit de bolso: o essencial do cofre num pen drive (ou cartao SD), para usar SEM este PC.

  O que faz
    - Escolhe as bibliotecas na ordem de catalogo\kit-de-bolso.json (primeiros socorros, portugues, agua e
      comida, consertos...) ate encher o espaco livre. A que nao cabe e pulada e a seguinte, menor, ainda pode
      entrar. Em FAT32, arquivos acima de 4 GB ficam de fora (formatar o pen drive em exFAT resolve).
    - Copia conferindo: le a biblioteca do cofre calculando o SHA-256 (o cofre e conferido contra o download)
      e depois rele a copia DIRETO do pen drive, sem passar pela memoria do Windows. Copia que estragou no
      caminho, ou pen drive falsificado (que diz ter mais espaco do que tem), nao passa.
    - Poe junto: o leitor Kiwix (Windows e Linux), ABRA-ME.html (passo a passo para iPhone, Android e PC),
      Emergencia.html (numeros e primeiros socorros), SHA256SUMS com o conferidor e, so com -ComFicha, a ficha
      medica da familia (dado pessoal: o pen drive pode se perder).
    - Rodar de novo atualiza: pula o que ja esta certo, copia o que falta ou mudou e poe versoes velhas em
      _para-apagar no proprio pen drive (nada e apagado: apague voce com Shift+Delete).

  Uso
    .\kit-de-bolso.ps1 -Simular                 # so o plano: o que entra, o que fica de fora, tempo e custo
    .\kit-de-bolso.ps1                          # acha o pen drive, mostra o plano e pergunta antes de copiar
    .\kit-de-bolso.ps1 -Destino E:\ -Sim        # monta sem perguntar
    .\kit-de-bolso.ps1 -Destino D:\COFRE-IA\teste-kit -TamanhoGB 0.3 -Sim   # teste pequeno numa pasta
    -ComFicha     leva a ficha medica da familia (Ficha medica.html)
    -Reconferir   rele do pen drive ate o que ja estava conferido
    -Json         so o plano, em JSON (para a Central)
#>
param(
    [string]$Destino,
    [double]$TamanhoGB = 0,
    [switch]$Simular,
    [switch]$Sim,
    [switch]$ComFicha,
    [switch]$Reconferir,
    [switch]$Json
)
. "$PSScriptRoot\comum.ps1"

$PastaModelosKit  = Join-Path $Raiz 'docs\kit-de-bolso'
$ArquivoPlanoKit  = Join-Path $PastaCatalogo 'kit-de-bolso.json'
$ArquivoUltimoKit = Join-Path $PastaLogs 'kit-de-bolso.json'
$ArquivoFicha     = Join-Path $Raiz 'dev\historico\ficha-medica.json'
$PortaKit         = 8484
$LimiteFat32      = [int64]4294967295
$Bloco            = 4MB
$EscritaEstimada  = 7e6     # bytes/s de um pen drive USB 2.0 comum (medido: 6,4 MB/s gravando, 20 MB/s lendo)
$LeituraEstimada  = 20e6
# O ultimo kit num pen drive mediu a velocidade de verdade: a estimativa usa a dele.
$UltimoKit = Ler-Json $ArquivoUltimoKit
if ($UltimoKit -and $UltimoKit.removivel -and [double]$UltimoKit.mb_s -gt 0) { $EscritaEstimada = [double]$UltimoKit.mb_s * 1e6 }
$Utf8SemBom       = New-Object Text.UTF8Encoding $false

# Leitura direta do disco (FILE_FLAG_NO_BUFFERING): a memoria do Windows nao responde no lugar do pen drive,
# entao o SHA-256 confere o que esta gravado de verdade. O buffer vem do VirtualAlloc (alinhado, como exige).
if (-not ('CofreKit.LeitorDireto' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace CofreKit {
    public sealed class LeitorDireto : IDisposable {
        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        static extern SafeFileHandle CreateFileW(string nome, uint acesso, uint partilha, IntPtr seguranca, uint criacao, uint flags, IntPtr modelo);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool ReadFile(SafeFileHandle h, IntPtr buffer, uint quantos, out uint lidos, IntPtr sobreposto);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr VirtualAlloc(IntPtr endereco, UIntPtr tamanho, uint tipo, uint protecao);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool VirtualFree(IntPtr endereco, UIntPtr tamanho, uint tipo);
        public const int Tamanho = 4 * 1024 * 1024;
        readonly SafeFileHandle h;
        IntPtr buffer;
        public readonly byte[] Dados = new byte[Tamanho];
        public LeitorDireto(string caminho) {
            // GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, NO_BUFFERING | SEQUENTIAL_SCAN
            h = CreateFileW(caminho, 0x80000000, 1, IntPtr.Zero, 3, 0x20000000 | 0x08000000, IntPtr.Zero);
            if (h.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            buffer = VirtualAlloc(IntPtr.Zero, (UIntPtr)Tamanho, 0x3000, 0x04);
            if (buffer == IntPtr.Zero) { h.Dispose(); throw new OutOfMemoryException(); }
        }
        // Le o proximo bloco. Menos que Tamanho = fim do arquivo (nao chame de novo: o ponteiro ficou desalinhado).
        public int Ler() {
            uint lidos;
            if (!ReadFile(h, buffer, (uint)Tamanho, out lidos, IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error());
            if (lidos > 0) Marshal.Copy(buffer, Dados, 0, (int)lidos);
            return (int)lidos;
        }
        public void Dispose() {
            if (buffer != IntPtr.Zero) { VirtualFree(buffer, UIntPtr.Zero, 0x8000); buffer = IntPtr.Zero; }
            h.Dispose();
        }
    }
}
'@
}

# ---------- Utilidades ----------
function Texto-Tam([double]$bytes) {
    if ($bytes -lt 1e9) { return [string]::Format($CulturaBR, '{0:N0} MB', [math]::Max(1, $bytes / 1e6)) }
    return [string]::Format($CulturaBR, '{0:N1} GB', $bytes / 1e9)
}
function Texto-Duracao([double]$s) {
    if ($s -lt 90) { return "$([math]::Max(1, [math]::Round($s))) s" }
    if ($s -lt 5400) { return "$([math]::Round($s / 60)) min" }
    return [string]::Format($CulturaBR, '{0:N1} h', $s / 3600)
}
function Html([string]$t) { return [Net.WebUtility]::HtmlEncode($t) }
function Ler-Modelo($nome) { return [IO.File]::ReadAllText((Join-Path $PastaModelosKit $nome), [Text.Encoding]::UTF8) }
function Gravar-Texto($caminho, [string]$texto, [string]$fimDeLinha = '') {
    if ($fimDeLinha) { $texto = ($texto -replace "`r`n", "`n") -replace "`n", $fimDeLinha }
    [IO.File]::WriteAllText($caminho, $texto, $Utf8SemBom)
}
function Hex($bytes) { return -join ($bytes | ForEach-Object { $_.ToString('x2') }) }
function Progresso([string]$rotulo, [int64]$feito, [int64]$total, $relogio) {
    $s = $relogio.Elapsed.TotalSeconds
    if ($s -le 0 -or $total -le 0) { return }
    $vel = $feito / $s
    $falta = if ($vel -gt 0) { ($total - $feito) / $vel } else { 0 }
    Info ([string]::Format($CulturaBR, '{0} {1:N0}% | {2:N1} MB/s | falta ~{3}', $rotulo, 100.0 * $feito / $total, $vel / 1e6, (Texto-Duracao $falta)))
}

# ---------- Onde montar ----------
function Achar-Destino {
    if ($Destino) {
        $d = [IO.Path]::GetFullPath($Destino)
    } else {
        $rem = @([IO.DriveInfo]::GetDrives() | Where-Object { $_.DriveType -eq 'Removable' -and $_.IsReady })
        if ($rem.Count -eq 0) { throw 'Nenhum pen drive ligado. Ligue o pen drive (ou cartao SD), ou diga onde montar: -Destino E:\' }
        if ($rem.Count -gt 1) { throw "Ha $($rem.Count) pen drives ligados ($(($rem | ForEach-Object { $_.Name.TrimEnd('\') }) -join ', ')). Diga qual: -Destino E:\" }
        $d = $rem[0].Name
    }
    if ($d -notmatch '^[A-Za-z]:\\') { throw "O destino precisa ser um disco deste PC com letra (ex.: E:\): $d" }
    $letra = $d.Substring(0, 1).ToUpper()
    $raizDisco = "${letra}:\"
    $info = New-Object IO.DriveInfo $raizDisco
    if (-not $info.IsReady) { throw "O disco ${letra}: nao esta pronto (desligado?)." }
    $ehRaiz = ($d.TrimEnd('\') + '\') -eq $raizDisco
    $removivel = ($info.DriveType -eq 'Removable')
    if ($letra -eq 'C') { throw 'O C: e pessoal: o kit nao vai para ele. Use o pen drive (ex.: -Destino E:\).' }
    if ($letra -eq $Raiz.Substring(0, 1).ToUpper()) { throw "O ${letra}: e o proprio cofre: o kit e para levar em outro disco (o pen drive)." }
    if (-not $removivel -and $ehRaiz) { throw "O ${letra}: nao e um pen drive. Para testar num disco fixo, use uma pasta (ex.: -Destino ${letra}:\COFRE-IA\teste-kit)." }
    $rc = Raiz-Cofre
    if ($rc) {
        foreach ($proibida in @('conhecimento', 'modelos', 'motores') | ForEach-Object { Join-Path $rc $_ }) {
            if ($d.StartsWith($proibida, [StringComparison]::OrdinalIgnoreCase)) { throw "O destino fica dentro do acervo do cofre ($proibida). Use outra pasta." }
        }
    }
    $base = if ($ehRaiz) { $raizDisco } else { $d.TrimEnd('\') }
    return [pscustomobject]@{
        Base = $base; Letra = $letra; Removivel = $removivel; EhRaiz = $ehRaiz
        Sistema = $info.DriveFormat; Rotulo = $info.VolumeLabel; Total = [int64]$info.TotalSize; Livre = [int64]$info.AvailableFreeSpace
    }
}

function Livre-Agora($dest) { return [int64](New-Object IO.DriveInfo "$($dest.Letra):\").AvailableFreeSpace }

# ---------- O plano: o que entra, na ordem de prioridade ----------
function Escolher($candidatos, [int64]$capacidade, [int64]$limite) {
    $dentro = New-Object Collections.ArrayList
    $fora = New-Object Collections.ArrayList
    [int64]$usado = 0
    foreach ($c in $candidatos) {
        if ($limite -gt 0 -and $c.tamanho -gt $limite) { [void]$fora.Add([pscustomobject]@{ item = $c; motivo = 'maior que 4 GB (pen drive em FAT32)' }); continue }
        if ($usado + $c.tamanho -le $capacidade) { [void]$dentro.Add($c); $usado += $c.tamanho }
        else { [void]$fora.Add([pscustomobject]@{ item = $c; motivo = 'nao coube' }) }
    }
    return [pscustomobject]@{ dentro = $dentro; fora = $fora; usado = $usado }
}

function Tamanho-Leitores {
    [int64]$t = 0
    $pw = Pasta-Motor 'kiwix-tools'
    if ($pw) { Get-ChildItem -LiteralPath $pw -File | Where-Object { $_.Name -eq 'kiwix-serve.exe' -or $_.Name -like 'icu*.dll' } | ForEach-Object { $t += $_.Length } }
    return $t + 60MB   # + o leitor de Linux (~30 MB) e as paginas, com folga
}

function Montar-Plano($dest) {
    $cfg = Ler-Json $ArquivoPlanoKit
    if (-not $cfg) { throw "Nao achei a ordem do kit: $ArquivoPlanoKit" }
    $cat = Ler-Catalogo
    $est = Ler-Estado
    $doCatalogo = @{}
    foreach ($c in @($cat.conhecimento)) { $doCatalogo[[string]$c.id] = $c }
    $grupos = New-Object Collections.ArrayList
    foreach ($g in @($cfg.grupos)) { [void]$grupos.Add([pscustomobject]@{ nome = [string]$g.nome; ids = @($g.ids) }) }
    if ($cfg.incluir_o_resto) {
        $listados = @{}
        foreach ($g in $grupos) { foreach ($id in $g.ids) { $listados[$id] = 1 } }
        $resto = @($est.conhecimento.Keys | Where-Object { -not $listados.ContainsKey($_) } | Sort-Object { [int64]$est.conhecimento[$_].tamanho })
        if ($resto.Count) { [void]$grupos.Add([pscustomobject]@{ nome = 'Outras do cofre'; ids = $resto }) }
    }
    $candidatos = New-Object Collections.ArrayList
    $naoBaixadas = New-Object Collections.ArrayList
    $vistos = @{}
    foreach ($g in $grupos) {
        foreach ($id in $g.ids) {
            if ($vistos.ContainsKey($id)) { continue }
            $vistos[$id] = 1
            $c = $doCatalogo[$id]
            $nome = if ($c -and $c.nome) { [string]$c.nome } else { $id }
            $e = $est.conhecimento[$id]
            if (-not $e -or -not $e.arquivo -or -not $e.sha256) { [void]$naoBaixadas.Add($nome); continue }
            $origem = Caminho-Absoluto $e.destino $e.local
            if (-not (Test-Path -LiteralPath $origem)) { [void]$naoBaixadas.Add($nome); continue }
            [void]$candidatos.Add([pscustomobject]@{
                id = $id; grupo = $g.nome; nome = $nome; uso = $(if ($c) { [string]$c.uso } else { '' })
                arquivo = [string]$e.arquivo; tamanho = [int64]$e.tamanho; sha256 = ([string]$e.sha256).ToLower(); origem = $origem
            })
        }
    }

    $pastaBib = Join-Path $dest.Base 'Bibliotecas'
    $existentes = @{}
    if (Test-Path -LiteralPath $pastaBib) { Get-ChildItem -LiteralPath $pastaBib -File | ForEach-Object { $existentes[$_.Name] = [int64]$_.Length } }
    $porArquivo = @{}
    foreach ($c in $candidatos) { $porArquivo[$c.arquivo] = $c }
    # Espaco que o kit pode usar: o livre + o que ja e dele (bibliotecas do plano e copias pela metade).
    [int64]$reuso = 0
    foreach ($n in $existentes.Keys) {
        $semParcial = $n -replace '\.parcial$', ''
        if ($porArquivo.ContainsKey($semParcial)) { $reuso += $existentes[$n] }
    }
    [int64]$margem = [math]::Max([int64]$cfg.margem_minima_mb * 1MB, [int64]($dest.Total * 0.01))
    [int64]$leitores = Tamanho-Leitores
    $pastaProg = Join-Path $dest.Base 'Programas'
    if (Test-Path -LiteralPath $pastaProg) { Get-ChildItem -LiteralPath $pastaProg -Recurse -File | ForEach-Object { $leitores -= $_.Length } }
    $leitores = [math]::Max(0, $leitores)
    $limite = if ($dest.Sistema -eq 'FAT32') { $LimiteFat32 } else { [int64]0 }
    [int64]$teto = if ($TamanhoGB -gt 0) { [int64]($TamanhoGB * 1e9) } else { [int64]::MaxValue }

    # Uma biblioteca que ja esta no pen drive mas sai do plano continua ocupando espaco (vai para _para-apagar):
    # recalcula ate o plano parar de mudar.
    [int64]$presos = 0
    for ($volta = 0; $volta -lt 6; $volta++) {
        [int64]$cap = [math]::Min($teto, $dest.Livre + $reuso - $presos - $margem - $leitores)
        $escolha = Escolher $candidatos $cap $limite
        $noPlano = @{}
        foreach ($c in $escolha.dentro) { $noPlano[$c.arquivo] = 1 }
        [int64]$novos = 0
        foreach ($n in $existentes.Keys) {
            $semParcial = $n -replace '\.parcial$', ''
            if ($porArquivo.ContainsKey($semParcial) -and -not $noPlano.ContainsKey($semParcial)) { $novos += $existentes[$n] }
        }
        if ($novos -eq $presos) { break }
        $presos = $novos
    }

    # O que ja esta no destino e o manifesto diz que foi conferido nao e copiado nem relido de novo.
    $manifesto = Ler-Json (Join-Path $pastaProg 'manifesto.json')
    $jaConferidos = @{}
    if ($manifesto) { foreach ($b in @($manifesto.bibliotecas)) { if ($b.arquivo) { $jaConferidos[[string]$b.arquivo] = [string]$b.sha256 } } }
    [int64]$aCopiar = 0; [int64]$aConferir = 0
    foreach ($c in $escolha.dentro) {
        if ($existentes[$c.arquivo] -ne $c.tamanho) { $aCopiar += $c.tamanho; $aConferir += $c.tamanho }
        elseif ($jaConferidos[$c.arquivo] -ne $c.sha256) { $aConferir += $c.tamanho }
    }
    $segundos = $aCopiar / $EscritaEstimada + $aConferir / $LeituraEstimada
    $e = Energia-Catalogo
    $watts = $e.tarefas.'kit-de-bolso'.watts
    if (-not $watts) { $watts = $e.pc_parado_w }
    return [pscustomobject]@{
        dest = $dest; grupos = @($grupos | ForEach-Object { $_.nome }); dentro = $escolha.dentro; fora = $escolha.fora
        total = $escolha.usado; naoBaixadas = $naoBaixadas; existentes = $existentes; margem = $margem
        aCopiar = $aCopiar; segundos = $segundos; watts = [double]$watts; wh = [double]$watts * $segundos / 3600
    }
}

function Descrever-Destino($dest) {
    $tipo = if ($dest.Removivel) { "pen drive $($dest.Rotulo)" } else { 'pasta de teste' }
    return "$($dest.Base)  ($tipo, $($dest.Sistema), $(Texto-Tam $dest.Total); $(Texto-Tam $dest.Livre) livres)"
}

function Mostrar-Plano($plano) {
    Titulo 'Kit de bolso'
    Info "Destino: $(Descrever-Destino $plano.dest)"
    if ($plano.dest.Sistema -eq 'NTFS' -and $plano.dest.Removivel) {
        Aviso 'O pen drive esta em NTFS: o iPhone nao grava (e talvez nem leia) NTFS. Para o iPhone, formate em exFAT.'
    }
    if ($plano.dentro.Count -eq 0) { Aviso 'Nenhuma biblioteca coube.'; return }
    Info ''
    Info "Cabem $($plano.dentro.Count) bibliotecas, $(Texto-Tam $plano.total), nesta ordem:"
    foreach ($g in $plano.grupos) {
        $itens = @($plano.dentro | Where-Object { $_.grupo -eq $g })
        if (-not $itens.Count) { continue }
        $soma = ($itens | Measure-Object tamanho -Sum).Sum
        Write-Host ("    {0}  ({1}, {2})" -f $g, $itens.Count, (Texto-Tam $soma)) -ForegroundColor Cyan
        foreach ($i in $itens) {
            $ja = if ($plano.existentes[$i.arquivo] -eq $i.tamanho) { '  [ja no destino]' } else { '' }
            Info ("  {0,-62} {1,8}{2}" -f $(if ($i.nome.Length -gt 62) { $i.nome.Substring(0, 61) + '.' } else { $i.nome }), (Texto-Tam $i.tamanho), $ja)
        }
    }
    if ($plano.fora.Count) {
        $somaFora = ($plano.fora | ForEach-Object { $_.item.tamanho } | Measure-Object -Sum).Sum
        Info ''
        Info "Ficam no cofre de casa: $($plano.fora.Count) bibliotecas, $(Texto-Tam $somaFora)."
        $primeiras = @($plano.fora | Select-Object -First 8)
        foreach ($f in $primeiras) { Info ("  {0,-62} {1,8}  ({2})" -f $(if ($f.item.nome.Length -gt 62) { $f.item.nome.Substring(0, 61) + '.' } else { $f.item.nome }), (Texto-Tam $f.item.tamanho), $f.motivo) }
        if ($plano.fora.Count -gt $primeiras.Count) { Info "  ... e mais $($plano.fora.Count - $primeiras.Count) (as maiores)." }
    }
    if ($plano.naoBaixadas.Count) { Info "Da lista, ainda nao baixadas no cofre: $($plano.naoBaixadas -join ', ')." }
    Info ''
    if ($ComFicha) { Info 'Ficha medica: vai junto (Ficha medica.html). Dado pessoal: se o pen drive se perder, a ficha vai junto.' }
    else { Info 'Ficha medica: nao vai (dado pessoal). Para levar, rode com -ComFicha.' }
    Info ([string]::Format($CulturaBR, 'Tempo estimado: ~{0} (copia a ~{1:N1} MB/s e releitura para conferir; depende do pen drive).', (Texto-Duracao $plano.segundos), $EscritaEstimada / 1e6))
    Mostrar-Estimativa 'kit-de-bolso' (Texto-Custo $plano.wh)
}

function Plano-Json($plano) {
    return [ordered]@{
        destino = $plano.dest.Base; rotulo = $plano.dest.Rotulo; sistema = $plano.dest.Sistema; removivel = $plano.dest.Removivel
        disco_bytes = $plano.dest.Total; livre_bytes = $plano.dest.Livre; bytes = $plano.total; a_copiar = $plano.aCopiar
        segundos = [math]::Round($plano.segundos); wh = [math]::Round($plano.wh, 1); ficha = [bool]$ComFicha
        cabem = @($plano.dentro | ForEach-Object { [ordered]@{ id = $_.id; nome = $_.nome; grupo = $_.grupo; bytes = $_.tamanho } })
        fora = @($plano.fora | ForEach-Object { [ordered]@{ id = $_.item.id; nome = $_.item.nome; bytes = $_.item.tamanho; motivo = $_.motivo } })
    }
}

# ---------- Copiar e conferir ----------
function Hash-Direto([string]$caminho, [int64]$tamanho, [string]$rotulo) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $relogio = [Diagnostics.Stopwatch]::StartNew()
    try {
        try { $leitor = [CofreKit.LeitorDireto]::new($caminho) }
        catch { return [pscustomobject]@{ hash = (Hash-Arquivo $caminho); direto = $false; segundos = $relogio.Elapsed.TotalSeconds } }
        try {
            [int64]$lido = 0; $proximo = 20
            while ($true) {
                $n = $leitor.Ler()
                if ($n -gt 0) { [void]$sha.TransformBlock($leitor.Dados, 0, $n, $null, 0); $lido += $n }
                if ($relogio.Elapsed.TotalSeconds -ge $proximo) { Progresso $rotulo $lido $tamanho $relogio; $proximo += 20 }
                if ($n -lt [CofreKit.LeitorDireto]::Tamanho) { break }
            }
        } finally { $leitor.Dispose() }
        [void]$sha.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        return [pscustomobject]@{ hash = (Hex $sha.Hash); direto = $true; segundos = $relogio.Elapsed.TotalSeconds }
    } finally { $sha.Dispose() }
}

function Copiar-Conferindo($item, [string]$final) {
    $parcial = "$final.parcial"
    $sha = [Security.Cryptography.SHA256]::Create()
    $buf = New-Object byte[] $Bloco
    $relogio = [Diagnostics.Stopwatch]::StartNew()
    [int64]$feito = 0; [int64]$desdeGravar = 0; $proximo = 20
    try {
        $ent = [IO.FileStream]::new($item.origem, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read, 1MB, [IO.FileOptions]::SequentialScan)
        try {
            $sai = [IO.FileStream]::new($parcial, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None, 1MB)
            try {
                while (($n = $ent.Read($buf, 0, $buf.Length)) -gt 0) {
                    [void]$sha.TransformBlock($buf, 0, $n, $null, 0)
                    $sai.Write($buf, 0, $n)
                    $feito += $n; $desdeGravar += $n
                    # Grava de verdade no pen drive a cada 64 MB: sem isso o Windows junta gigabytes na memoria e
                    # o andamento mostra 100% enquanto o pen drive ainda escreve por minutos.
                    if ($desdeGravar -ge 64MB) { $sai.Flush($true); $desdeGravar = 0 }
                    if ($relogio.Elapsed.TotalSeconds -ge $proximo) { Progresso '    copiando  ' $feito $item.tamanho $relogio; $proximo += 20 }
                }
                $sai.Flush($true)   # tudo no pen drive antes de conferir
            } finally { $sai.Dispose() }
        } finally { $ent.Dispose() }
        [void]$sha.TransformFinalBlock($buf, 0, 0)
        $hashOrigem = Hex $sha.Hash
    } finally { $sha.Dispose() }
    $segCopia = $relogio.Elapsed.TotalSeconds
    if ($hashOrigem -ne $item.sha256) { return [pscustomobject]@{ ok = $false; motivo = 'origem'; parcial = $parcial } }
    $conf = Hash-Direto $parcial $item.tamanho '    conferindo'
    if ($conf.hash -ne $item.sha256) { return [pscustomobject]@{ ok = $false; motivo = 'copia'; parcial = $parcial } }
    return [pscustomobject]@{ ok = $true; parcial = $parcial; segCopia = $segCopia; segConf = $conf.segundos; direto = $conf.direto }
}

function Mover-ParaApagar($base, [string]$caminho) {
    $pasta = Join-Path $base '_para-apagar'
    New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    $nome = Split-Path $caminho -Leaf
    $alvo = Join-Path $pasta $nome
    if (Test-Path -LiteralPath $alvo) { $alvo = Join-Path $pasta ("{0}-{1}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $nome) }
    Move-Item -LiteralPath $caminho -Destination $alvo
}

function Copiar-Leitores($pastaProg) {
    $origemWin = Pasta-Motor 'kiwix-tools'
    if (-not $origemWin) { throw 'O leitor Kiwix (kiwix-tools) nao esta instalado no cofre: menu, opcao 15, ou instalar-motores.ps1.' }
    $win = Join-Path $pastaProg 'windows'
    New-Item -ItemType Directory -Force -Path $win | Out-Null
    foreach ($f in Get-ChildItem -LiteralPath $origemWin -File | Where-Object { $_.Name -eq 'kiwix-serve.exe' -or $_.Name -like 'icu*.dll' }) {
        $alvo = Join-Path $win $f.Name
        if (-not (Test-Path -LiteralPath $alvo) -or (Get-Item -LiteralPath $alvo).Length -ne $f.Length) { Copy-Item -LiteralPath $f.FullName -Destination $alvo -Force }
    }
    $linux = 'nao'
    $origemLinux = Pasta-Motor 'kiwix-tools-linux'
    $tgz = if ($origemLinux) { Get-ChildItem -LiteralPath $origemLinux -Filter '*.tar.gz' -File | Select-Object -First 1 } else { $null }
    if ($tgz) {
        $lin = Join-Path $pastaProg 'linux'
        New-Item -ItemType Directory -Force -Path $lin | Out-Null
        $membro = @(Executar-Nativo 'tar.exe' @('-tzf', $tgz.FullName) | Where-Object { $_ -match '/kiwix-serve$' }) | Select-Object -First 1
        if ($membro) {
            Executar-Nativo 'tar.exe' @('-xzf', $tgz.FullName, '-C', $lin, '--strip-components=1', $membro) | Out-Null
            if (Test-Path -LiteralPath (Join-Path $lin 'kiwix-serve')) { $linux = 'sim' }
        }
    }
    return [pscustomobject]@{ versao = (Split-Path $origemWin -Leaf); linux = $linux }
}

function Html-Ficha($f) {
    $sb = New-Object Text.StringBuilder
    foreach ($p in @($f.pessoas)) {
        $alergia = [string]$p.alergias
        $linhas = @(
            [pscustomobject]@{ r = 'Alergias'; v = $(if ($alergia) { $alergia } else { 'nenhuma anotada' }); c = $(if ($alergia) { ' class="alergia"' } else { '' }) }
            [pscustomobject]@{ r = 'Rem&eacute;dios cont&iacute;nuos'; v = [string]$p.remedios; c = '' }
            [pscustomobject]@{ r = 'Condi&ccedil;&otilde;es'; v = [string]$p.condicoes; c = '' }
            [pscustomobject]@{ r = 'Tipo sangu&iacute;neo'; v = [string]$p.sangue; c = '' }
            [pscustomobject]@{ r = 'Nascimento ou idade'; v = [string]$p.nascimento; c = '' }
            [pscustomobject]@{ r = 'Observa&ccedil;&otilde;es'; v = [string]$p.observacoes; c = '' }
        )
        [void]$sb.Append("<section class=""pessoa""><h2>$(Html $p.nome)</h2><dl>")
        foreach ($l in $linhas) { if ($l.v) { [void]$sb.Append("<dt>$($l.r)</dt><dd$($l.c)>$(Html $l.v)</dd>") } }
        [void]$sb.Append('</dl></section>')
    }
    $contatos = @($f.contatos)
    if ($contatos.Count) {
        [void]$sb.Append('<section class="pessoa"><h2>Contatos de emerg&ecirc;ncia</h2><dl>')
        foreach ($c in $contatos) {
            $quem = (@([string]$c.nome, [string]$c.relacao) | Where-Object { $_ }) -join ', '
            if (-not $quem) { $quem = 'Contato' }
            $tel = [string]$c.telefone
            $num = $tel -replace '[^\d+]', ''
            $dd = if ($tel) { "<a href=""tel:$num"">$(Html $tel)</a>" } else { '&mdash;' }
            [void]$sb.Append("<dt>$(Html $quem)</dt><dd>$dd</dd>")
        }
        [void]$sb.Append('</dl></section>')
    }
    if ($f.ponto_encontro) { [void]$sb.Append("<section class=""pessoa""><h2>Ponto de encontro</h2><p style=""margin:0"">$(Html $f.ponto_encontro)</p></section>") }
    return $sb.ToString()
}

function Gravar-Paginas($plano, $base, $pastaProg, [bool]$fichaVai) {
    $data = (Get-Date).ToString('dd/MM/yyyy')
    $n = $plano.dentro.Count
    $palavra = if ($n -eq 1) { 'biblioteca' } else { 'bibliotecas' }
    $resumo = "<b>$n $palavra</b> ($(Texto-Tam $plano.total)) de primeiros socorros, &aacute;gua e comida, consertos e consulta."
    $sb = New-Object Text.StringBuilder
    foreach ($g in $plano.grupos) {
        $itens = @($plano.dentro | Where-Object { $_.grupo -eq $g })
        if (-not $itens.Count) { continue }
        $soma = ($itens | Measure-Object tamanho -Sum).Sum
        $rot = if ($itens.Count -eq 1) { '1 biblioteca' } else { "$($itens.Count) bibliotecas" }
        [void]$sb.Append("<section class=""cartao grupo""><h3>$(Html $g)<small>$rot &middot; $(Texto-Tam $soma)</small></h3><ul class=""itens"">")
        foreach ($i in $itens) {
            [void]$sb.Append("<li><span class=""nome"">$(Html $i.nome)</span><span class=""tam"">$(Texto-Tam $i.tamanho)</span>")
            if ($i.uso) { [void]$sb.Append("<span class=""uso"">$(Html $i.uso)</span>") }
            [void]$sb.Append('</li>')
        }
        [void]$sb.Append("</ul></section>`n")
    }
    if ($plano.fora.Count) {
        $somaFora = ($plano.fora | ForEach-Object { $_.item.tamanho } | Measure-Object -Sum).Sum
        $fb = New-Object Text.StringBuilder
        [void]$fb.Append("<p class=""dica"">$($plano.fora.Count) bibliotecas ($(Texto-Tam $somaFora)) n&atilde;o couberam neste pen drive e continuam no SSD e no HD de casa:</p><ul class=""fora"">")
        foreach ($f in $plano.fora) { [void]$fb.Append("<li>$(Html $f.item.nome) &middot; $(Texto-Tam $f.item.tamanho)</li>") }
        [void]$fb.Append('</ul>')
        $fora = $fb.ToString()
    } else {
        $fora = '<p class="dica" style="margin:0">Tudo o que o cofre tem coube aqui.</p>'
    }
    if ($fichaVai) {
        $ficha = '<p class="dica">Alergias, rem&eacute;dios, tipo sangu&iacute;neo e contatos de quem mora com voc&ecirc;. Dado pessoal: guarde o pen drive com cuidado.</p><a class="botao" href="Ficha medica.html">Abrir a ficha m&eacute;dica</a>'
    } else {
        $ficha = '<p style="margin:0">N&atilde;o vem neste pen drive: fica s&oacute; no computador de casa, porque &eacute; dado pessoal. No iPhone, use a Ficha M&eacute;dica do app Sa&uacute;de (veja &ldquo;No iPhone&rdquo;).</p>'
    }
    $disco = if ($plano.dest.Removivel) { "Pen drive $(Html $plano.dest.Rotulo), $($plano.dest.Sistema), $(Texto-Tam $plano.dest.Total)." } else { "Pasta $(Html $plano.dest.Base)." }
    $abra = (Ler-Modelo 'ABRA-ME.html').Replace('{{RESUMO}}', $resumo).Replace('{{GRUPOS}}', $sb.ToString()).Replace('{{FORA}}', $fora).
        Replace('{{FICHA}}', $ficha).Replace('{{DISCO}}', $disco).Replace('{{DATA}}', $data).Replace('{{PORTA}}', [string]$PortaKit)
    Gravar-Texto (Join-Path $base 'ABRA-ME.html') $abra
    Gravar-Texto (Join-Path $base 'Emergencia.html') ((Ler-Modelo 'Emergencia.html').Replace('{{DATA}}', $data))
    Gravar-Texto (Join-Path $base 'Abrir a biblioteca.cmd') (Ler-Modelo 'Abrir a biblioteca.cmd') "`r`n"
    Gravar-Texto (Join-Path $pastaProg 'conferir.cmd') (Ler-Modelo 'conferir.cmd') "`r`n"
    Gravar-Texto (Join-Path $pastaProg 'conferir.ps1') (Ler-Modelo 'conferir.ps1') "`r`n"
    Gravar-Texto (Join-Path $pastaProg 'abrir-biblioteca-linux.sh') (Ler-Modelo 'abrir-biblioteca-linux.sh') "`n"
}

function Gravar-Ficha($base) {
    $f = Ler-Json $ArquivoFicha
    if (-not $f -or (-not @($f.pessoas).Count -and -not @($f.contatos).Count)) {
        Aviso 'A ficha medica esta vazia: preencha na Central (botao SOS > Ficha medica > Editar) e rode de novo.'
        return $false
    }
    $atualizada = if ($f.atualizada) { "Atualizada em $(([datetime]$f.atualizada).ToString('dd/MM/yyyy'))." } else { '' }
    $html = (Ler-Modelo 'ficha-medica.html').Replace('{{CONTEUDO}}', (Html-Ficha $f)).Replace('{{ATUALIZADA}}', $atualizada).Replace('{{DATA}}', (Get-Date).ToString('dd/MM/yyyy'))
    Gravar-Texto (Join-Path $base 'Ficha medica.html') $html
    return $true
}

function Gravar-Conferencia($base, $pastaProg, $registros) {
    $linhas = New-Object Collections.ArrayList
    foreach ($r in $registros) { [void]$linhas.Add("$($r.sha256)  Bibliotecas/$($r.arquivo)") }
    $outros = @(Get-ChildItem -LiteralPath $pastaProg -Recurse -File | Where-Object { $_.Name -notin 'SHA256SUMS.txt', 'manifesto.json' })
    foreach ($nome in 'ABRA-ME.html', 'Emergencia.html', 'Abrir a biblioteca.cmd', 'Ficha medica.html') {
        $p = Join-Path $base $nome
        if (Test-Path -LiteralPath $p) { $outros += Get-Item -LiteralPath $p }
    }
    $prefixo = $base.TrimEnd('\') + '\'
    foreach ($f in $outros) { [void]$linhas.Add("$(Hash-Arquivo $f.FullName)  $($f.FullName.Substring($prefixo.Length).Replace('\', '/'))") }
    Gravar-Texto (Join-Path $pastaProg 'SHA256SUMS.txt') (($linhas -join "`n") + "`n") "`n"
}

# ---------- Principal ----------
try {
    $dest = Achar-Destino
    $plano = Montar-Plano $dest
} catch {
    if ($Json) { [Console]::Out.Write((ConvertTo-Json -Compress @{ erro = $_.Exception.Message })); exit 1 }
    Aviso $_.Exception.Message
    exit 1
}
if ($Json) { [Console]::Out.Write((ConvertTo-Json -Compress -Depth 6 (Plano-Json $plano))); exit 0 }

Mostrar-Plano $plano
if ($Simular -or $plano.dentro.Count -eq 0) { exit 0 }
if (-not $Sim) {
    $r = Read-Host "  Montar o kit em $($dest.Base) agora? (s/n)"
    if ($r -notmatch '^\s*[sS]') { Info 'Nada foi copiado.'; exit 0 }
}

# Um kit por vez: duas copias no mesmo pen drive se atropelariam (e a conferencia acusaria erro de gravacao).
$script:TravaKit = New-Object System.Threading.Mutex($false, 'Global\SSD-IA-kit-de-bolso')
if (-not $script:TravaKit.WaitOne(0)) { Aviso 'Ja ha um kit sendo montado (outra janela). Espere ele terminar.'; exit 1 }
$inicio = Get-Date
try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch {}   # o jogo e o resto do PC primeiro
Manter-Acordado
$base = $dest.Base
$pastaBib = Join-Path $base 'Bibliotecas'
$pastaProg = Join-Path $base 'Programas'
New-Item -ItemType Directory -Force -Path $pastaBib, $pastaProg | Out-Null

# O que estava no pen drive e saiu do plano (versao velha, biblioteca trocada): para _para-apagar, nunca apagado.
$noPlano = @{}
foreach ($i in $plano.dentro) { $noPlano[$i.arquivo] = 1 }
$afastados = 0
foreach ($f in Get-ChildItem -LiteralPath $pastaBib -File) {
    $semParcial = $f.Name -replace '\.parcial$', ''
    if ($f.Name -like '*.parcial' -and $noPlano.ContainsKey($semParcial)) { continue }   # reaproveitado na copia
    if (-not $noPlano.ContainsKey($f.Name)) { Mover-ParaApagar $base $f.FullName; $afastados++ }
}

$anteriores = @{}
$manifestoVelho = Ler-Json (Join-Path $pastaProg 'manifesto.json')
if ($manifestoVelho) { foreach ($b in @($manifestoVelho.bibliotecas)) { if ($b.arquivo) { $anteriores[[string]$b.arquivo] = $b } } }

Titulo 'Copiando e conferindo'
$registros = New-Object Collections.ArrayList
$falhas = New-Object Collections.ArrayList
$parou = $false
[int64]$copiados = 0; $segCopia = 0.0
$i = 0
foreach ($item in $plano.dentro) {
    $i++
    Write-Host ("  [{0}/{1}] {2} ({3})" -f $i, $plano.dentro.Count, $item.nome, (Texto-Tam $item.tamanho))
    $final = Join-Path $pastaBib $item.arquivo
    $agora = (Get-Date).ToString('s')
    if (Test-Path -LiteralPath $final) {
        $f = Get-Item -LiteralPath $final
        $antes = $anteriores[$item.arquivo]
        if ($f.Length -eq $item.tamanho -and -not $Reconferir -and $antes -and [string]$antes.sha256 -eq $item.sha256 -and
            [string]$antes.gravado -eq $f.LastWriteTimeUtc.ToString('o')) {
            Ok 'ja estava no destino, conferido antes'
            [void]$registros.Add([ordered]@{ id = $item.id; nome = $item.nome; grupo = $item.grupo; arquivo = $item.arquivo; tamanho = $item.tamanho; sha256 = $item.sha256; conferido_em = [string]$antes.conferido_em; gravado = [string]$antes.gravado })
            continue
        }
        if ($f.Length -eq $item.tamanho) {
            $c = Hash-Direto $final $item.tamanho '    conferindo'
            if ($c.hash -eq $item.sha256) {
                Ok 'ja estava no destino (conferido agora)'
                [void]$registros.Add([ordered]@{ id = $item.id; nome = $item.nome; grupo = $item.grupo; arquivo = $item.arquivo; tamanho = $item.tamanho; sha256 = $item.sha256; conferido_em = $agora; gravado = $f.LastWriteTimeUtc.ToString('o') })
                continue
            }
        }
        Aviso 'a copia que estava no destino nao confere: vai para _para-apagar e copio de novo'
        Mover-ParaApagar $base $final
    }
    $parcialVelho = "$final.parcial"
    [int64]$aproveita = if (Test-Path -LiteralPath $parcialVelho) { (Get-Item -LiteralPath $parcialVelho).Length } else { 0 }
    if ((Livre-Agora $dest) + $aproveita - $item.tamanho -lt [math]::Min($plano.margem, 64MB)) {
        Aviso 'sem espaco no destino agora: ficou de fora'
        [void]$falhas.Add("$($item.nome): sem espaco")
        continue
    }
    $r = Copiar-Conferindo $item $final
    if (-not $r.ok -and $r.motivo -eq 'copia') {
        Aviso 'a releitura do destino nao bateu com o original: copiando de novo'
        $r = Copiar-Conferindo $item $final
    }
    if (-not $r.ok) {
        if ($r.motivo -eq 'origem') {
            Aviso 'a biblioteca no cofre esta diferente do download (estragou?): ficou de fora. Rode a integridade (menu, opcao 16).'
            [void]$falhas.Add("$($item.nome): diferente no cofre")
            continue
        }
        Aviso 'O destino gravou errado duas vezes seguidas: o pen drive pode estar com defeito (ou ser falsificado). Parei aqui.'
        [void]$falhas.Add("$($item.nome): o destino grava errado")
        $parou = $true
        break
    }
    Move-Item -LiteralPath $r.parcial -Destination $final
    $copiados += $item.tamanho; $segCopia += $r.segCopia
    $vel = if ($r.segCopia -gt 0) { $item.tamanho / $r.segCopia / 1e6 } else { 0 }
    $modo = if ($r.direto) { 'relido do disco' } else { 'relido (pode ter vindo da memoria)' }
    Ok ([string]::Format($CulturaBR, 'copiado a {0:N1} MB/s e conferido ({1})', $vel, $modo))
    [void]$registros.Add([ordered]@{ id = $item.id; nome = $item.nome; grupo = $item.grupo; arquivo = $item.arquivo; tamanho = $item.tamanho; sha256 = $item.sha256; conferido_em = $agora; gravado = (Get-Item -LiteralPath $final).LastWriteTimeUtc.ToString('o') })
}

Titulo 'Leitor, paginas e conferencia'
$leitor = Copiar-Leitores $pastaProg
Ok "Leitor Kiwix $($leitor.versao) para Windows$(if ($leitor.linux -eq 'sim') { ' e Linux' })"
$fichaVai = $false
if ($ComFicha) { $fichaVai = Gravar-Ficha $base }
elseif (Test-Path -LiteralPath (Join-Path $base 'Ficha medica.html')) {
    Aviso 'Uma ficha medica de um kit anterior continua no destino (Ficha medica.html). Se nao quiser leva-la, apague com Shift+Delete.'
}
# A lista de paginas mostra so o que esta de fato no destino.
$planoFinal = $plano.PSObject.Copy()
$conferidos = @{}
foreach ($r in $registros) { $conferidos[$r.arquivo] = 1 }
$planoFinal.dentro = @($plano.dentro | Where-Object { $conferidos.ContainsKey($_.arquivo) })
$planoFinal.total = [int64](($planoFinal.dentro | Measure-Object tamanho -Sum).Sum)
$foraFinal = New-Object Collections.ArrayList
foreach ($f in $plano.fora) { [void]$foraFinal.Add($f) }
foreach ($x in @($plano.dentro | Where-Object { -not $conferidos.ContainsKey($_.arquivo) })) { [void]$foraFinal.Add([pscustomobject]@{ item = $x; motivo = 'falhou na copia' }) }
$planoFinal.fora = $foraFinal
Gravar-Paginas $planoFinal $base $pastaProg $fichaVai
Ok 'ABRA-ME.html, Emergencia.html e "Abrir a biblioteca"'
if ($fichaVai) { Ok 'Ficha medica.html' }

$manifesto = [ordered]@{
    kit = 'Cofre de bolso'; montado_em = (Get-Date).ToString('s'); sistema_de_arquivos = $dest.Sistema
    leitor = "kiwix-tools $($leitor.versao)"; porta = $PortaKit; ficha = $fichaVai
    bibliotecas = @($registros)
}
Salvar-Json $manifesto (Join-Path $pastaProg 'manifesto.json')
Gravar-Conferencia $base $pastaProg $registros
Ok 'SHA256SUMS.txt e manifesto.json (para conferir em qualquer PC: Programas\conferir)'

$segundos = ((Get-Date) - $inicio).TotalSeconds
$mbs = if ($segCopia -gt 0) { [math]::Round($copiados / $segCopia / 1e6, 1) } else { 0 }
$ok = (-not $parou) -and $falhas.Count -eq 0
Salvar-Json ([ordered]@{
    montado_em = (Get-Date).ToString('s'); destino = $base; rotulo = $dest.Rotulo; sistema = $dest.Sistema; removivel = $dest.Removivel
    bibliotecas = $registros.Count; bytes = $planoFinal.total; ids = @($registros | ForEach-Object { $_.id })
    fora = @($foraFinal | ForEach-Object { $_.item.id }); ficha = $fichaVai; ok = $ok; falhas = @($falhas)
    segundos = [math]::Round($segundos); copiados_bytes = $copiados; mb_s = $mbs; afastados = $afastados
}) $ArquivoUltimoKit

Titulo 'Pronto'
Info "$($registros.Count) bibliotecas, $(Texto-Tam $planoFinal.total), conferidas em $($dest.Base)."
if ($copiados -gt 0) { Info ([string]::Format($CulturaBR, 'Copiado agora: {0} a {1:N1} MB/s.', (Texto-Tam $copiados), $mbs)) }
if ($afastados) { Info "$afastados arquivo(s) velho(s) foram para _para-apagar no destino: apague com Shift+Delete para liberar espaco." }
foreach ($f in $falhas) { Aviso $f }
if ($dest.Removivel) { Info 'Antes de tirar o pen drive, use "Ejetar" no Explorador de Arquivos.' }
Info 'No pen drive, abra o ABRA-ME.html: passo a passo para iPhone, Android e PC.'
Mostrar-GastoFinal 'kit-de-bolso' $inicio
if (-not $ok) { exit 2 }
