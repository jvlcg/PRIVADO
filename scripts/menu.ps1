# Menu do cofre de IAs. Abra com dois cliques em A:\IA.cmd
# Gravado em UTF-8 com BOM: e assim que o PowerShell 5.1 le os acentos e as bordas.
# -SoMostrar desenha o menu uma vez e sai (para conferir o visual).
param([switch]$SoMostrar)
. "$PSScriptRoot\comum.ps1"
$ErrorActionPreference = 'Continue'

function Nova-Janela($script, $argumentos = '') {
    # Servidores abrem em janela própria para o menu continuar livre.
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSScriptRoot\$script`" $argumentos"
}

# Cada opção: número, grupo, nome, tarefa (para a estimativa de energia do catálogo) e o que faz.
$opcoes = @(
    @{ n = 1;  grupo = 'USAR NO DIA A DIA'; nome = 'Central do Cofre no navegador (o jeito mais fácil)'; tarefa = 'central'
       acao = { Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\central.ps1`"" } }
    @{ n = 2;  grupo = 'USAR NO DIA A DIA'; nome = 'Chat com todos os modelos'; tarefa = 'chat'
       acao = { Nova-Janela 'iniciar-servidor.ps1' } }
    @{ n = 3;  grupo = 'USAR NO DIA A DIA'; nome = 'Biblioteca offline: Wikipédia, medicina, manuais, fóruns'; tarefa = 'biblioteca'
       acao = { Nova-Janela 'iniciar-biblioteca.ps1' } }
    @{ n = 4;  grupo = 'USAR NO DIA A DIA'; nome = 'Perguntar (só buscar, rápida ou com fonte)'; tarefa = 'perguntar'
       acao = { $q = Read-Host '  Sua pergunta'; if ($q) { Perguntar-ComModo $q } } }
    @{ n = 5;  grupo = 'USAR NO DIA A DIA'; nome = 'Conselho de IAs: várias IAs decidem juntas'; tarefa = 'conselho'
       acao = { Nova-Janela 'conselho.ps1' '-Servir' } }

    @{ n = 6;  grupo = 'CRIAR'; nome = 'Imagem, vídeo, música e 3D (ComfyUI)'; tarefa = 'comfyui'
       acao = { Nova-Janela 'iniciar-comfyui.ps1' } }
    @{ n = 7;  grupo = 'CRIAR'; nome = 'Gerar imagem ou vídeo pelo terminal (ComfyUI aberto)'; tarefa = 'gerar'
       acao = {
           $tipo = Read-Host '  Imagem (i) ou vídeo (v)?'
           $texto = Read-Host '  Descreva (de preferência em inglês)'
           if ($texto -and $tipo -eq 'v') { & "$PSScriptRoot\gerar.ps1" -Video $texto }
           elseif ($texto) { & "$PSScriptRoot\gerar.ps1" -Imagem $texto }
       } }
    @{ n = 8;  grupo = 'CRIAR'; nome = 'Transcrever áudio (Whisper)'; tarefa = 'transcrever'
       acao = { $f = Read-Host '  Caminho do arquivo de áudio (WAV)'; if ($f) { & "$PSScriptRoot\transcrever.ps1" -Audio $f.Trim('"') } } }
    @{ n = 9;  grupo = 'CRIAR'; nome = 'Falar um texto em voz alta (Piper)'; tarefa = 'falar'
       acao = { $texto = Read-Host '  Texto para falar'; if ($texto) { & "$PSScriptRoot\falar.ps1" $texto -Tocar } } }

    @{ n = 10; grupo = 'ENERGIA'; nome = 'Medir o consumo do PC (1 minuto parado)'; tarefa = 'medir'
       acao = { & "$PSScriptRoot\medir-energia.ps1" -Segundos 60 | Out-Null } }
    @{ n = 11; grupo = 'ENERGIA'; nome = 'Fechar tudo e liberar a placa de vídeo'; tarefa = 'fechar'
       acao = { & "$PSScriptRoot\parar-tudo.ps1" } }
    @{ n = 12; grupo = 'ENERGIA'; nome = 'Modo jogo: desliga todas as IAs (liga e desliga)'; tarefa = 'modo-jogo'
       acao = { & "$PSScriptRoot\modo-jogo.ps1" } }

    @{ n = 13; grupo = 'MANTER'; nome = 'Status do acervo (o que tem e o que está aberto)'; tarefa = 'status'
       acao = { & "$PSScriptRoot\status.ps1" } }
    @{ n = 14; grupo = 'MANTER'; nome = 'Verificar novidades e atualizações'; tarefa = 'verificar'
       acao = { & "$PSScriptRoot\verificar-atualizacoes.ps1" } }
    @{ n = 15; grupo = 'MANTER'; nome = 'Sincronizar o cofre (baixa o que falta e confere)'; tarefa = 'sincronizar'
       acao = { Nova-Janela 'sincronizar-cofre.ps1' } }
    @{ n = 16; grupo = 'MANTER'; nome = 'Conferir a integridade completa (SHA256)'; tarefa = 'integridade'
       acao = { & "$PSScriptRoot\verificar-integridade.ps1" } }
    @{ n = 17; grupo = 'MANTER'; nome = 'Ver o catálogo de modelos e bibliotecas'; tarefa = 'catalogo'
       acao = { & "$PSScriptRoot\baixar-modelo.ps1" -Listar; & "$PSScriptRoot\baixar-conhecimento.ps1" -Listar } }
    @{ n = 18; grupo = 'MANTER'; nome = 'Testar o projeto (sem rodar modelos)'; tarefa = 'testar'
       acao = { & "$PSScriptRoot\testar-cofre.ps1" } }
    @{ n = 19; grupo = 'MANTER'; nome = 'Desligar o PC sozinho quando ficar parado (vigia)'; tarefa = 'vigia'
       acao = {
           & "$PSScriptRoot\desligar-ao-terminar.ps1" -Status
           $r = Read-Host '  l = ligar a vigia, p = parar, Enter = voltar'
           if ($r -eq 'l') { Nova-Janela 'desligar-ao-terminar.ps1' }
           elseif ($r -eq 'p') { & "$PSScriptRoot\desligar-ao-terminar.ps1" -Parar }
       } }
)
# Palavras que acham cada opção quando você digita uma palavra em vez do número.
$chaves = @{
    1 = 'central painel navegador site inicio'; 2 = 'chat conversar modelo modelos ia'; 3 = 'biblioteca wikipedia livros manual kiwix forum'
    4 = 'perguntar pergunta fonte resposta buscar'; 5 = 'conselho debate opiniao decidir decisao'; 6 = 'comfyui imagem video musica 3d criar desenho'
    7 = 'gerar imagem video'; 8 = 'transcrever audio whisper legenda'; 9 = 'falar voz piper ler alto'
    10 = 'medir energia consumo watts conta'; 11 = 'fechar parar liberar placa'; 12 = 'jogo jogar game'
    13 = 'status acervo aberto'; 14 = 'verificar novidades atualizacoes atualizar'; 15 = 'sincronizar baixar backup'
    16 = 'integridade sha256 conferir'; 17 = 'catalogo lista modelos'; 18 = 'testar teste testes'; 19 = 'desligar vigia ocioso dormir'
}
# No modo jogo só funcionam as opções que não ligam IA nem pesam no PC.
$livresNoJogo = 1, 10, 11, 12, 13, 17, 18, 19

function Sem-Acento([string]$s) {
    $d = $s.ToLowerInvariant().Normalize([Text.NormalizationForm]::FormD)
    return -join ($d.ToCharArray() | Where-Object { [Globalization.CharUnicodeInfo]::GetUnicodeCategory($_) -ne 'NonSpacingMark' })
}

# Opção 4: o jeito mais barato que resolve. Só buscar não liga IA; a rápida usa uma IA pequena.
function Perguntar-ComModo([string]$q) {
    Write-Host ''
    foreach ($m in @(@('1', 'Só buscar na biblioteca, sem IA', 'buscar'), @('2', 'Resposta rápida, sem fontes', 'rapida'), @('3', 'Com fonte, citando a biblioteca', 'perguntar'))) {
        Write-Host "    $($m[0])  " -ForegroundColor Yellow -NoNewline
        Write-Host $m[1].PadRight(40) -NoNewline
        Write-Host (Texto-Estimativa $m[2]) -ForegroundColor DarkGray
    }
    $modo = @{ '1' = 'buscar'; '2' = 'rapida' }[(Read-Host '  Como responder? (Enter = 3)').Trim()]
    if (-not $modo) { $modo = 'fonte' }
    & "$PSScriptRoot\perguntar.ps1" $q -Modo $modo
}

# Digitou palavras em vez do número: as opções cujo nome ou palavras-chave contêm todas elas.
function Achar-Opcoes([string]$texto) {
    $termos = @((Sem-Acento $texto) -split '\s+' | Where-Object { $_.Length -ge 2 })
    if ($termos.Count -eq 0) { return @() }
    return @($opcoes | Where-Object {
        $alvo = Sem-Acento "$($_.nome) $($chaves[$_.n])"
        @($termos | Where-Object { $alvo.Contains($_) }).Count -eq $termos.Count
    })
}

$largura = 100
function Linha-Opcao($o) {
    Write-Host ('  {0,3}  ' -f $o.n) -ForegroundColor Yellow -NoNewline
    Write-Host ($o.nome.PadRight(56)) -NoNewline
    Write-Host (Texto-Estimativa $o.tarefa) -ForegroundColor DarkGray
}

function Mostrar-Menu {
    $e = Energia-Catalogo
    $borda = '─' * ($largura - 4)
    Write-Host ''
    Write-Host "  ┌$borda┐" -ForegroundColor Cyan
    $titulo = '  COFRE DE IAs'
    $direita = 'funciona sem internet  '
    Write-Host ('  │' + $titulo.PadRight($largura - 4 - $direita.Length) + $direita + '│') -ForegroundColor Cyan
    Write-Host "  └$borda┘" -ForegroundColor Cyan
    Write-Host ([string]::Format($CulturaBR, '  Tarifa: {0}, R$ {1:N2}/kWh   ·   PC ligado sem uso: {2}', $e.distribuidora, (Tarifa-Kwh), (Texto-Estimativa 'pc-ligado'))) -ForegroundColor DarkGray
    Write-Host "  Gasto do cofre neste mês: $(Texto-GastoMes)" -ForegroundColor DarkGray
    if (ModoJogo-Ativo) {
        Write-Host ''
        Write-Host '  MODO JOGO LIGADO: as IAs estão desligadas e não abrem. Escolha 12 para sair.' -ForegroundColor Black -BackgroundColor Yellow
    }
    $grupo = ''
    foreach ($o in $opcoes) {
        if ($o.grupo -ne $grupo) {
            $grupo = $o.grupo
            Write-Host ''
            Write-Host ('  ' + $grupo.PadRight(61)) -ForegroundColor Cyan -NoNewline
            if ($grupo -eq 'USAR NO DIA A DIA') { Write-Host 'energia estimada' -ForegroundColor DarkCyan } else { Write-Host '' }
        }
        Linha-Opcao $o
    }
    Write-Host ''
    Write-Host '    0  ' -ForegroundColor Yellow -NoNewline
    Write-Host 'Sair'
    Write-Host ''
    Write-Host '  Dica: digite o número, uma palavra (biblioteca, jogo, energia...) ou já a sua pergunta.' -ForegroundColor DarkGray
}

if ($SoMostrar) { Mostrar-Menu; return }
while ($true) {
    Mostrar-Menu
    $op = (Read-Host '  Escolha').Trim()
    if ($op -eq '0' -or $op -eq 'sair') { return }
    if (-not $op) { continue }
    $o = $opcoes | Where-Object { [string]$_.n -eq $op } | Select-Object -First 1
    if (-not $o -and $op -notmatch '^\d+$') {
        $achadas = @(Achar-Opcoes $op)
        if ($achadas.Count -eq 1) { $o = $achadas[0] }
        elseif ($achadas.Count -gt 1) {
            Write-Host "  Com ""$op"":" -ForegroundColor Cyan
            foreach ($a in $achadas) { Linha-Opcao $a }
            Read-Host '  Enter para voltar ao menu' | Out-Null
            continue
        } elseif (@($op -split '\s+').Count -ge 3) {
            # Várias palavras e nenhuma opção: é uma pergunta.
            if (ModoJogo-Ativo) { Write-Host '  Modo jogo ligado: as IAs estão desligadas. Escolha 12 para sair do modo jogo.' -ForegroundColor Yellow; continue }
            Write-Host ''
            Write-Host "  Pergunta: $op" -ForegroundColor Cyan
            try { Perguntar-ComModo $op } catch { Write-Host "  Erro: $($_.Exception.Message)" -ForegroundColor Red }
            continue
        }
    }
    if (-not $o) { Write-Host "  Nada com ""$op"". Digite o número da opção." -ForegroundColor Red; continue }
    if ((ModoJogo-Ativo) -and $livresNoJogo -notcontains $o.n) {
        Write-Host '  Modo jogo ligado: esta opção liga IA ou pesa no PC. Escolha 12 para sair do modo jogo.' -ForegroundColor Yellow
        continue
    }
    Write-Host ''
    Write-Host "  $($o.n). $($o.nome)" -ForegroundColor Cyan
    Mostrar-Estimativa $o.tarefa
    try { & $o.acao } catch { Write-Host "  Erro: $($_.Exception.Message)" -ForegroundColor Red }
}
