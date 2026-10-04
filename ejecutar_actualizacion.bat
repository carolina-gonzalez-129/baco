@echo off
REM ==============================================================================
REM RUTINA DE ACTUALIZACIÓN AUTOMÁTICA DE ARTÍCULOS - BACO
REM Orden: 1. Sincronizar -> 2. Normalizar/Hashes -> 3. Embeddings
REM ==============================================================================

cd /d "%~dp0"
set "LOG_FILE=%~dp0actualizar_articulos.log"

echo. >> "%LOG_FILE%"
echo ======================================================== >> "%LOG_FILE%"
echo Pipeline iniciado: %DATE% %TIME% >> "%LOG_FILE%"
echo ======================================================== >> "%LOG_FILE%"

REM --------------------------------------------------------------------------
REM Paso 1: Sincronizar articulos desde Discourse (solo datos crudos)
REM --------------------------------------------------------------------------
echo [1/3] Sincronizando articulos desde Discourse...
echo [1/3] Sincronizando articulos desde Discourse... >> "%LOG_FILE%"
".venv\Scripts\python.exe" -m baco.server.discourse.actualizar_nuevos_articulos >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Fallo la sincronizacion desde Discourse. Codigo: %ERRORLEVEL%
    echo [ERROR] Fallo la sincronizacion desde Discourse. Codigo: %ERRORLEVEL% >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)

REM --------------------------------------------------------------------------
REM Paso 2: Normalizar texto/titulo y actualizar hashes (e invalidar embeddings si hubo cambios)
REM --------------------------------------------------------------------------
echo [2/3] Normalizando y actualizando hashes...
echo [2/3] Normalizando y actualizando hashes... >> "%LOG_FILE%"
".venv\Scripts\python.exe" baco\server\db\rellenar_normalizados.py >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Fallo la normalizacion y calculo de hashes. Codigo: %ERRORLEVEL%
    echo [ERROR] Fallo la normalizacion y calculo de hashes. Codigo: %ERRORLEVEL% >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)

REM --------------------------------------------------------------------------
REM Paso 3: Generar embeddings locales para pendientes (sentence-transformers)
REM --------------------------------------------------------------------------
echo [3/3] Generando embeddings pendientes...
echo [3/3] Generando embeddings pendientes... >> "%LOG_FILE%"
".venv\Scripts\python.exe" baco\server\db\generar_embeddings.py >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Fallo la generacion de embeddings. Codigo: %ERRORLEVEL%
    echo [ERROR] Fallo la generacion de embeddings. Codigo: %ERRORLEVEL% >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)

echo ======================================================== >> "%LOG_FILE%"
echo Pipeline finalizado con exito: %DATE% %TIME% >> "%LOG_FILE%"
echo ======================================================== >> "%LOG_FILE%"
echo [EXITO] Pipeline completado exitosamente.
