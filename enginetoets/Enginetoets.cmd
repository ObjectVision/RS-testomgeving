@echo off
rem Enginetoets.cmd: dubbelklik en het venster van de enginetoets opent (model-RSopen#16).
rem Vraagt PowerShell 7 (pwsh); zonder pwsh zegt dit script dat en stopt het.
where pwsh >nul 2>nul
if errorlevel 1 (
    echo PowerShell 7 ^(pwsh^) is niet gevonden. Installeer het van https://aka.ms/powershell en start dit bestand opnieuw.
    pause
    exit /b 1
)
start "Enginetoets" /min pwsh -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0Enginetoets.ps1"
