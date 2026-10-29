@echo off
rem Abre a Central do Cofre no navegador (dois cliques neste arquivo).
start "Central do Cofre" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\central.ps1"
