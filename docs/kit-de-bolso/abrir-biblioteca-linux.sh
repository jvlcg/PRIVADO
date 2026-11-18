#!/bin/sh
# Cofre de bolso: abre as bibliotecas do pen drive num PC com Linux (64 bits), sem internet.
# Uso, num terminal na pasta do pen drive:  sh Programas/abrir-biblioteca-linux.sh
# Pen drives em exFAT/FAT nao guardam a permissao de executar: o leitor e copiado para uma pasta temporaria
# so sua (mktemp -d, ninguem mais mexe nela) e a copia some quando a biblioteca fecha.
cd "$(dirname "$0")/.." || exit 1
PORTA=8484
PASTA=$(mktemp -d) || { echo "Nao deu para criar a pasta temporaria."; exit 1; }
trap 'rm -rf "$PASTA"' EXIT
trap 'exit 130' INT TERM
EXE="$PASTA/kiwix-serve"
cp Programas/linux/kiwix-serve "$EXE" && chmod 700 "$EXE" || { echo "Nao deu para preparar o leitor."; exit 1; }
echo
echo "  Cofre de bolso: abrindo a biblioteca em http://127.0.0.1:$PORTA"
echo "  Para fechar, aperte Ctrl+C nesta janela."
echo
( sleep 3; xdg-open "http://127.0.0.1:$PORTA/" >/dev/null 2>&1 || true ) &
"$EXE" --address=127.0.0.1 --port=$PORTA --blockexternal --skipInvalid --nodatealiases Bibliotecas/*.zim
