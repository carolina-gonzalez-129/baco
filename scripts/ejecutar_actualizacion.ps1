# ==============================================================================
#   Rutina de actualizacion automatica
# USo :
#   .\scripts\ejecutar_actualizacion.ps1                      (diario)
#   .\scripts\ejecutar_actualizacion.ps1 -Completo            (semanal)
#   .\scripts\ejecutar_actualizacion.ps1 -Reintento
#   .\scripts\ejecutar_actualizacion.ps1 -ProgramarHora "03:00" (registrar la task, ver q coincida con el horario de la api de finnegans)
# ==============================================================================
[CmdletBinding()]
param (
    [switch]$Completo,
    [switch]$Reintento,
    [string]$ProgramarHora = ""
)

$ProjectRoot = (Get-Item "$PSScriptRoot\..").FullName
Set-Location $ProjectRoot

$LogsDir    = Join-Path $ProjectRoot "logs"
$LogFile    = Join-Path $LogsDir "actualizar_articulos.log"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

if ($ProgramarHora) {
    Write-Host "[*] Registrando tarea en el Programador de Tareas de Windows..." -ForegroundColor Cyan
    $Action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`""
    $Trigger = New-ScheduledTaskTrigger -Daily -At $ProgramarHora
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

    Register-ScheduledTask `
        -TaskName "Baco_Actualizacion_Discourse" `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Description "Actualización automática de artículos Discourse en BACO" `
        -Force | Out-Null

    Write-Host "[ÉXITO] Tarea programada en Windows para correr todos los días a las $ProgramarHora hs." -ForegroundColor Green
    exit 0
}

function Log-Msg {
    param (
        [string]$Mensaje,
        [string]$Color = "White"
    )
    $Timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $LineaLog = "[$Timestamp] $Mensaje"
    Write-Host $Mensaje -ForegroundColor $Color
    Add-Content -Path $LogFile -Value $LineaLog -Encoding utf8
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if ($Completo) {
    $ModoTipo = "semanal"
    $SyncArgs = @("--completo", "--purgar")
} else {
    $ModoTipo = "diario"
    $SyncArgs = @()
}

$MarkerFile = Join-Path $ProjectRoot ".last_success_$ModoTipo"
$HoyIso     = (Get-Date).ToString("yyyy-MM-dd")

if ($Reintento) {
    if (Test-Path $MarkerFile) {
        $UltimoExito = (Get-Content -Path $MarkerFile -Raw).Trim()
        if ($UltimoExito -eq $HoyIso) {
            Log-Msg "[INFO] La sincronización [$ModoTipo] ya se ejecutó exitosamente hoy ($HoyIso). Omitiendo reintento." "Yellow"
            exit 0
        }
    }
}

if (-not (Test-Path $VenvPython)) {
    Log-Msg "[ERROR] No se encontró el ejecutable de Python en: $VenvPython" "Red"
    exit 1
}

Add-Content -Path $LogFile -Value "`n========================================================" -Encoding utf8
Log-Msg "Pipeline iniciado (modo: $ModoTipo, reintento: $($Reintento.IsPresent))" "Cyan"
Add-Content -Path $LogFile -Value "========================================================" -Encoding utf8

#Sincronizar nuevos codigo 0 ok 1 algunos temas fallaron 2 error grave
Log-Msg "[1/3] Sincronizando artículos nuevos desde Discourse..." "Yellow"
& $VenvPython -m baco.server.discourse.actualizar_nuevos_articulos @SyncArgs *>> $LogFile
$SyncRc = $LASTEXITCODE

if ($SyncRc -ge 2) {
    Log-Msg "[ERROR] Falló la sincronización desde Discourse. Código: $SyncRc" "Red"
    exit $SyncRc
}
if ($SyncRc -eq 1) {
    Log-Msg "[AVISO] Algunos temas no se pudieron sincronizar. Ver log. Se continúa con el pipeline." "Magenta"
}

#Sincronizar editados
Log-Msg "[2/3] Sincronizando artículos editados desde Discourse..." "Yellow"
& $VenvPython -m baco.server.discourse.actualizar_articulos_editados *>> $LogFile
$EditRc = $LASTEXITCODE

if ($EditRc -ge 2) {
    Log-Msg "[ERROR] Falló la sincronización de editados desde Discourse. Código: $EditRc" "Red"
    exit $EditRc
}
if ($EditRc -eq 1) {
    Log-Msg "[AVISO] Algunos temas editados no se pudieron sincronizar. Ver log. Se continúa con el pipeline." "Magenta"
}

#Generar embeddings locales pendients
Log-Msg "[3/3] Generando embeddings pendientes (título y texto sin headers)..." "Yellow"
& $VenvPython -m baco.server.db.generar_embeddings *>> $LogFile
$EmbRc = $LASTEXITCODE

if ($EmbRc -ne 0) {
    Log-Msg "[ERROR] Falló la generación de embeddings. Código: $EmbRc" "Red"
    exit $EmbRc
}

Add-Content -Path $LogFile -Value "========================================================" -Encoding utf8
Log-Msg "Pipeline finalizado con éxito." "Green"
Add-Content -Path $LogFile -Value "========================================================" -Encoding utf8

Set-Content -Path $MarkerFile -Value $HoyIso -NoNewline -Encoding utf8

Log-Msg "Se completo exitosamente el pipeline" "Green"
exit 0
