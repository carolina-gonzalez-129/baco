@echo off
REM ==============================================================================
REM RUTINA DE ACTUALIZACIÓN AUTOMÁTICA DE ARTÍCULOS - BACO
REM Orden: 1. Sincronizar -> 2. Normalizar/Hashes -> 3. Embeddings
REM Uso:
REM   ejecutar_actualizacion.bat            -> solo artículos nuevos (diario)
REM   ejecutar_actualizacion.bat completo   -> re-descarga todo: detecta editados y borrados (semanal)
REM ==============================================================================

cd /d "%~dp0"
set "LOG_FILE=%~dp0actualizar_articulos.log"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "SYNC_ARGS="
if /i "%~1"=="completo" set "SYNC_ARGS=--completo"

echo. >> "%LOG_FILE%"
echo ======================================================== >> "%LOG_FILE%"
echo Pipeline iniciado: %DATE% %TIME% (modo: %~1) >> "%LOG_FILE%"
echo ======================================================== >> "%LOG_FILE%"

REM --------------------------------------------------------------------------
REM Paso 1: Sincronizar articulos desde Discourse (solo datos crudos)
REM   Codigo 0 = OK | 1 = algunos temas fallaron (se continua) | 2+ = error grave
REM --------------------------------------------------------------------------
echo [1/3] Sincronizando articulos desde Discourse...
echo [1/3] Sincronizando articulos desde Discourse... >> "%LOG_FILE%"
".venv\Scripts\python.exe" -m baco.server.discourse.actualizar_nuevos_articulos %SYNC_ARGS% >> "%LOG_FILE%" 2>&1
set "SYNC_RC=%ERRORLEVEL%"
if %SYNC_RC% geq 2 (
    echo [ERROR] Fallo la sincronizacion desde Discourse. Codigo: %SYNC_RC%
    echo [ERROR] Fallo la sincronizacion desde Discourse. Codigo: %SYNC_RC% >> "%LOG_FILE%"
    exit /b %SYNC_RC%
)
if %SYNC_RC% equ 1 (
    echo [AVISO] Algunos temas no se pudieron sincronizar. Ver log. Se continua con el pipeline.
    echo [AVISO] Algunos temas no se pudieron sincronizar. Se continua con el pipeline. >> "%LOG_FILE%"
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
