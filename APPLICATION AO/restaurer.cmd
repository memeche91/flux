@echo off
rem D'Aplomb : double-cliquez sur ce fichier pour lancer restaurer.ps1.
rem La fenetre reste ouverte a la fin, meme si Windows refuse de lancer le script : son message reste lisible.
set DAPLOMB_LANCEUR=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restaurer.ps1"
if errorlevel 1 (
  echo.
  echo La restauration s'est arretee : lisez le message ci-dessus, ou envoyez une capture de cette fenetre.
)
echo.
pause
