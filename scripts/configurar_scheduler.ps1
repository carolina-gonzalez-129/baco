# ==============================================================================
# CONFIGURADOR DE HORARIOS EN WINDOWS TASK SCHEDULER - BACO
# Diario lu a vier a las 10 (sincronizacion incremental)
# semanal sabados a las 10 (sincronizacion completa)
#  Modo de uso :
#   .\scripts\configurar_scheduler.ps1              -> instala y actualiza ambas tareas
#   .\scripts\configurar_scheduler.ps1 -Consultar   -> muestra el estado y cuando se ejecutara de nuevo
# ==============================================================================
[CmdletBinding()]
param (
    [switch]$Consultar,
    [switch]$Desinstalar
)

$TaskNameDiaria  = "Baco_Discourse_Actualizacion_Diaria"
$TaskNameSemanal = "Baco_Discourse_Actualizacion_Semanal"

# CONSULTA OPCION
if ($Consultar) {
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "   ESTADO DE TAREAS PROGRAMADAS - BACO                  " -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan
    foreach ($name in @($TaskNameDiaria, $TaskNameSemanal)) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) {
            $info = Get-ScheduledTaskInfo -TaskName $name
            Write-Host ""
            Write-Host "[*] Tarea: $name" -ForegroundColor Green
            Write-Host "   - Estado: $($task.State)"
            Write-Host "   - Ultima ejecucion: $($info.LastRunTime)"
            Write-Host "   - Ultimo resultado: $($info.LastTaskResult)"
            Write-Host "   - Proxima ejecucion: $($info.NextRunTime)"
        } else {
            Write-Host ""
            Write-Host "[-] Tarea no encontrada: $name" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Cyan
    exit 0
}

# INSTALACION DE TAREAS
$ProjectRoot = (Get-Item "$PSScriptRoot\..").FullName
$ScriptPath  = Join-Path $PSScriptRoot "ejecutar_actualizacion.ps1"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "No se encontro el script de actualizacion en: $ScriptPath"
    exit 1
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   CONFIGURANDO PROGRAMADOR DE TAREAS DE WINDOWS        " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# CREDENCIALES
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

# ENERGIA Y TIEMPO LMITE
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

#TASK 1 DIARIA EJECUCION P/ACTUALIZAR A LAS 10 DE LA MANIANA
Write-Host ""
Write-Host "[1/2] Programando tarea diaria (Lunes a Viernes a las 10:00 hs)..." -ForegroundColor Yellow
$ActionDiaria  = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""

$TriggerDiaria = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "10:00"

Register-ScheduledTask `
    -TaskName $TaskNameDiaria `
    -Action $ActionDiaria `
    -Trigger $TriggerDiaria `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Actualizacion diaria incremental de articulos Discourse en BACO" `
    -Force | Out-Null

Write-Host "   [OK] Tarea '$TaskNameDiaria' registrada con exito." -ForegroundColor Green

#TASK 2 DE FIN DE SEMANA ES COMPLETO
Write-Host ""
Write-Host "[2/2] Programando tarea semanal completa (Sabados a las 10:00 hs)..." -ForegroundColor Yellow
$ActionSemanal  = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`" -Completo"

$TriggerSemanal = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Saturday `
    -At "10:00"

Register-ScheduledTask `
    -TaskName $TaskNameSemanal `
    -Action $ActionSemanal `
    -Trigger $TriggerSemanal `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Actualizacion semanal completa y purga de articulos Discourse en BACO" `
    -Force | Out-Null

Write-Host "   [OK] Tarea '$TaskNameSemanal' registrada con exito." -ForegroundColor Green

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Ambas tasks quedaron configuradas en Windows." -ForegroundColor Green
Write-Host "   Lunes a viernes 10:00 hs -> Sincronizacion diaria"
Write-Host "   Sabados 10 hs -> Sincronizacion semanal (-Completo)"
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
