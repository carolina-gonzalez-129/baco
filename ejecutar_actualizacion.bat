@echo off
REM ==============================================================================
REM RUTINA DE ACTUALIZACIÓN AUTOMÁTICA DE ARTÍCULOS - BACO
REM Orden: 1. Nuevos -> 2. Editados -> 3. Embeddings pendientes
REM Uso:
REM   actualizar.bat (o ejecutar_actualizacion.bat)          -> incremental: nuevos y editados (diario)
REM   actualizar.bat completo                               -> re-descarga total (semanal)
REM ==============================================================================

cd /d "%~dp0"
set "LOG_FILE=%~dp0actualizar_articulos.log"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "ES_COMPLETO=0"
set "ES_REINTENTO=0"

for %%A in (%*) do (
    if /i "%%~A"=="completo" set "ES_COMPLETO=1"
    if /i "%%~A"=="--completo" set "ES_COMPLETO=1"
    if /i "%%~A"=="reintento" set "ES_REINTENTO=1"
    if /i "%%~A"=="--reintento" set "ES_REINTENTO=1"
)

if "%ES_COMPLETO%"=="1" (
    set "MODO_TIPO=semanal"
    set "SYNC_ARGS=--completo --purgar"
) else (
    set "MODO_TIPO=diario"
    set "SYNC_ARGS="
)

REM Si es una ejecucion en modo reintento, verificar si hoy ya termino con exito
if "%ES_REINTENTO%"=="1" (
    ".venv\Scripts\python.exe" -c "import sys, datetime, pathlib; mode = sys.argv[1]; f = pathlib.Path(f'.last_success_{mode}'); sys.exit(0 if f.exists() and f.read_text().strip() == datetime.date.today().isoformat() else 1)" "%MODO_TIPO%"
    if not errorlevel 1 (
        echo [INFO] La sincronizacion [%MODO_TIPO%] ya se ejecuto exitosamente hoy. Omitiendo reintento.
        echo [INFO] La sincronizacion [%MODO_TIPO%] ya se ejecuto exitosamente hoy. Omitiendo reintento. >> "%LOG_FILE%"
        exit /b 0
    )
)

echo. >> "%LOG_FILE%"
echo ======================================================== >> "%LOG_FILE%"
echo Pipeline iniciado: %DATE% %TIME% (modo: %MODO_TIPO%, reintento: %ES_REINTENTO%) >> "%LOG_FILE%"
echo ======================================================== >> "%LOG_FILE%"

REM --------------------------------------------------------------------------
REM Paso 1: Sincronizar articulos nuevos desde Discourse
REM   Codigo 0 = OK | 1 = algunos temas fallaron (se continua) | 2+ = error grave
REM --------------------------------------------------------------------------
echo [1/3] Sincronizando articulos nuevos desde Discourse...
echo [1/3] Sincronizando articulos nuevos desde Discourse... >> "%LOG_FILE%"
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
REM Paso 2: Sincronizar articulos editados desde Discourse (/posts.json)
REM --------------------------------------------------------------------------
echo [2/3] Sincronizando articulos editados desde Discourse...
echo [2/3] Sincronizando articulos editados desde Discourse... >> "%LOG_FILE%"
".venv\Scripts\python.exe" -m baco.server.discourse.actualizar_articulos_editados >> "%LOG_FILE%" 2>&1
set "EDIT_RC=%ERRORLEVEL%"
if %EDIT_RC% geq 2 (
    echo [ERROR] Fallo la sincronizacion de editados desde Discourse. Codigo: %EDIT_RC%
    echo [ERROR] Fallo la sincronizacion de editados desde Discourse. Codigo: %EDIT_RC% >> "%LOG_FILE%"
    exit /b %EDIT_RC%
)
if %EDIT_RC% equ 1 (
    echo [AVISO] Algunos temas editados no se pudieron sincronizar. Ver log. Se continua con el pipeline.
    echo [AVISO] Algunos temas editados no se pudieron sincronizar. Se continua con el pipeline. >> "%LOG_FILE%"
)

REM --------------------------------------------------------------------------
REM Paso 3: Generar embeddings locales pendientes (título y texto sin headers)
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

REM Registrar éxito de hoy para el modo actual (diario o semanal)
".venv\Scripts\python.exe" -c "import sys, datetime, pathlib; pathlib.Path(f'.last_success_{sys.argv[1]}').write_text(datetime.date.today().isoformat())" "%MODO_TIPO%"

echo [EXITO] Pipeline completado exitosamente.
