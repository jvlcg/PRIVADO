@echo off
rem Cofre de bolso: confere se algum arquivo do pen drive estragou (SHA-256).
title Cofre de bolso - conferir
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0conferir.ps1"
echo.
pause
