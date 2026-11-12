@echo off
title SyllabusAI
rem Funciona desde cualquier carpeta (Escritorio incluido): usa la ruta fija del proyecto.
set "PROYECTO=C:\Users\WIN10\Downloads\ProyectoTitulacion\Practica"
set "URL=http://127.0.0.1:8080"
cd /d "%PROYECTO%" 2>nul

if not exist "%PROYECTO%\.venv\Scripts\syllabusai.exe" (
    echo No se encontro SyllabusAI en %PROYECTO%
    echo Si movio la carpeta del proyecto, corrija la linea PROYECTO de este archivo.
    pause
    exit /b 1
)

rem Si el servidor ya esta corriendo, solo se abre el navegador. Un segundo servidor
rem no puede arrancar: la base vectorial local (Qdrant) admite un solo proceso a la vez.
netstat -ano | findstr /r /c:":8080 .*LISTENING" >nul
if not errorlevel 1 (
    echo SyllabusAI ya esta corriendo. Abriendo %URL% ...
    start "" %URL%
    timeout /t 3 /nobreak >nul
    exit /b 0
)

echo Iniciando SyllabusAI en %URL%
echo.
echo   Deje esta ventana abierta mientras use la web.
echo   Para apagarla: Ctrl+C o cierre la ventana.
echo   No haga clic dentro de esta ventana: Windows pausa el servidor mientras
echo   haya texto seleccionado (si pasa, presione Esc).
echo.

rem Abre el navegador unos segundos despues, cuando el servidor ya este listo.
start "" /b cmd /c "timeout /t 5 /nobreak >nul & start %URL%"

"%PROYECTO%\.venv\Scripts\syllabusai.exe" web

echo.
echo El servidor se detuvo.
pause
