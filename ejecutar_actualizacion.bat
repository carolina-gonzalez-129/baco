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
REM Paso 2: Verificar hashes, series (base_titulo), textos sin headers y STORED en Postgres
REM --------------------------------------------------------------------------
echo [2/3] Verificando hashes, series y textos limpios sin headers...
echo [2/3] Verificando hashes, series y textos limpios sin headers... >> "%LOG_FILE%"
".venv\Scripts\python.exe" -m baco.server.db.rellenar_normalizados >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Fallo la verificacion de hashes y normalizados. Codigo: %ERRORLEVEL%
    echo [ERROR] Fallo la verificacion de hashes y normalizados. Codigo: %ERRORLEVEL% >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)

REM --------------------------------------------------------------------------
REM Paso 3: Generar embeddings locales pendientes 
REM --------------------------------------------------------------------------
echo [3/3] Generando embeddings pendientes (titulo y texto sin headers)...
echo [3/3] Generando embeddings pendientes (titulo y texto sin headers)... >> "%LOG_FILE%"
".venv\Scripts\python.exe" -m baco.server.db.generar_embeddings >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Fallo la generacion de embeddings. Codigo: %ERRORLEVEL%
    echo [ERROR] Fallo la generacion de embeddings. Codigo: %ERRORLEVEL% >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)

echo ======================================================== >> "%LOG_FILE%"
echo Pipeline finalizado con exito: %DATE% %TIME% >> "%LOG_FILE%"
echo ======================================================== >> "%LOG_FILE%"
echo [EXITO] Pipeline completado exitosamente.
