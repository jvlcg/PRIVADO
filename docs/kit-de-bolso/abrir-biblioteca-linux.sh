#!/bin/sh
# Cofre de bolso: abre as bibliotecas do pen drive num PC com Linux (64 bits), sem internet.
# Uso, num terminal na pasta do pen drive:  sh Programas/abrir-biblioteca-linux.sh
# Pen drives em exFAT/FAT nao guardam a permissao de executar: o leitor e copiado para /tmp antes de abrir.
cd "$(dirname "$0")/.." || exit 1
PORTA=8484
EXE=/tmp/kiwix-serve-cofre-de-bolso
cp Programas/linux/kiwix-serve "$EXE" && chmod +x "$EXE" || { echo "Nao deu para preparar o leitor em /tmp."; exit 1; }
echo
echo "  Cofre de bolso: abrindo a biblioteca em http://127.0.0.1:$PORTA"
echo "  Para fechar, aperte Ctrl+C nesta janela."
echo
( sleep 3; xdg-open "http://127.0.0.1:$PORTA/" >/dev/null 2>&1 || true ) &
exec "$EXE" --address=127.0.0.1 --port=$PORTA --blockexternal --skipInvalid --nodatealiases Bibliotecas/*.zim
