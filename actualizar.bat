@echo off
REM ==============================================================================
REM ACCESO RÁPIDO PARA EL PIPELINE DE ACTUALIZACIÓN DE BACO
REM Uso:
REM   actualizar.bat           -> Sincroniza artículos nuevos y editados (diario)
REM   actualizar.bat completo  -> Sincronización completa (semanal)
REM ==============================================================================
call "%~dp0ejecutar_actualizacion.bat" %*
