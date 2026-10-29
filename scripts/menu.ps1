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
    @{ n = 3;  grupo = 'USAR NO DIA A DIA'; nome = 'Biblioteca offline: Wikipédia, mapa, medicina, manuais'; tarefa = 'biblioteca'
       acao = { Nova-Janela 'iniciar-biblioteca.ps1' } }
    @{ n = 4;  grupo = 'USAR NO DIA A DIA'; nome = 'Perguntar com fonte (IA + biblioteca)'; tarefa = 'perguntar'
       acao = { $q = Read-Host '  Sua pergunta'; if ($q) { & "$PSScriptRoot\perguntar.ps1" $q } } }
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
)
# No modo jogo só funcionam as opções que não ligam IA nem pesam no PC.
$livresNoJogo = 1, 10, 11, 12, 13, 17, 18

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
}

if ($SoMostrar) { Mostrar-Menu; return }
while ($true) {
    Mostrar-Menu
    $op = (Read-Host '  Escolha um número').Trim()
    if ($op -eq '0') { return }
    $o = $opcoes | Where-Object { [string]$_.n -eq $op } | Select-Object -First 1
    if (-not $o) { Write-Host '  Opção inválida.' -ForegroundColor Red; continue }
    if ((ModoJogo-Ativo) -and $livresNoJogo -notcontains $o.n) {
        Write-Host '  Modo jogo ligado: esta opção liga IA ou pesa no PC. Escolha 12 para sair do modo jogo.' -ForegroundColor Yellow
        continue
    }
    Write-Host ''
    Write-Host "  $($o.n). $($o.nome)" -ForegroundColor Cyan
    Mostrar-Estimativa $o.tarefa
    try { & $o.acao } catch { Write-Host "  Erro: $($_.Exception.Message)" -ForegroundColor Red }
}
