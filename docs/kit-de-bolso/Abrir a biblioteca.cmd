@echo off
rem Cofre de bolso: abre as bibliotecas do pen drive no navegador, sem internet e sem instalar nada.
rem O leitor (kiwix-serve) escuta so neste computador (127.0.0.1): nada fica aberto na rede.
setlocal enabledelayedexpansion
title Cofre de bolso - biblioteca
cd /d "%~dp0"
set PORTA=8484
set ARQS=
for %%f in ("Bibliotecas\*.zim") do set ARQS=!ARQS! "%%~f"
if not defined ARQS (
  echo.
  echo   Nenhuma biblioteca na pasta Bibliotecas deste pen drive.
  echo.
  pause
  exit /b 1
)
echo.
echo   Cofre de bolso: abrindo a biblioteca em http://127.0.0.1:%PORTA%
echo   O navegador abre sozinho em alguns segundos.
echo   Para fechar a biblioteca, feche esta janela.
echo.
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start http://127.0.0.1:%PORTA%/"
"Programas\windows\kiwix-serve.exe" --address=127.0.0.1 --port=%PORTA% --blockexternal --skipInvalid --nodatealiases !ARQS!
echo.
echo   A biblioteca fechou. Se foi sem querer, a porta %PORTA% pode estar em uso
echo   (outra biblioteca aberta?). Feche a outra e tente de novo.
echo.
pause
