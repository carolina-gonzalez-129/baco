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
REM Paso 2: Normalizar texto/titulo, asegurar columnas/indices (pg_trgm/texto_1000) y actualizar hashes
REM --------------------------------------------------------------------------
echo [2/3] Normalizando y actualizando hashes (texto_1000 y pg_trgm)...
echo [2/3] Normalizando y actualizando hashes (texto_1000 y pg_trgm)... >> "%LOG_FILE%"
".venv\Scripts\python.exe" -m baco.server.db.rellenar_normalizados >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Fallo la normalizacion y calculo de hashes. Codigo: %ERRORLEVEL%
    echo [ERROR] Fallo la normalizacion y calculo de hashes. Codigo: %ERRORLEVEL% >> "%LOG_FILE%"
    exit /b %ERRORLEVEL%
)

REM --------------------------------------------------------------------------
REM Paso 3: Generar embeddings locales para pendientes (Titulo: MiniLM 384d, Texto: E5 768d)
REM --------------------------------------------------------------------------
echo [3/3] Generando embeddings pendientes (titulo y texto)...
echo [3/3] Generando embeddings pendientes (titulo y texto)... >> "%LOG_FILE%"
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
