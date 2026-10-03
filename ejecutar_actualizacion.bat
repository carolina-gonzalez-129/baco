@echo off
REM ==============================================================================
REM RUTINA DE ACTUALIZACIÓN AUTOMÁTICA DE ARTÍCULOS - BACO
REM Se ejecuta todos los miercoles a las 11:00 AM mediante power shell

REM ==============================================================================

REM 1. Posicionarse en la carpeta raíz del proyecto
cd /d "C:\Users\ahreq\IdeaProjects\GeminiAgente"

REM 2. Registrar fecha y hora en el log
echo. >> "actualizar_articulos.log"
echo ======================================================== >> "actualizar_articulos.log"
echo Sincronizacion iniciada: %DATE% %TIME% >> "actualizar_articulos.log"
echo ======================================================== >> "actualizar_articulos.log"

REM 3. Ejecutar el script usando el Python del entorno virtual (.venv)
".venv\Scripts\python.exe" -m baco.server.discourse.actualizar_nuevos_articulos >> "actualizar_articulos.log" 2>&1

REM 4. Registrar finalización
echo Sincronizacion finalizada con codigo: %ERRORLEVEL% >> "actualizar_articulos.log"
echo. >> "actualizar_articulos.log"
