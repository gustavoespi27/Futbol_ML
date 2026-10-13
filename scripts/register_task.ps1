# Registra (o actualiza) la tarea programada de recolección diaria.
# Corre 3 veces al día; si el PC estaba apagado, se ejecuta al encenderlo (StartWhenAvailable).
# Uso: powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
# pythonw: corre sin abrir una ventana de consola (los registros quedan en logs\)
$python = Join-Path $root ".venv\Scripts\pythonw.exe"
$script = Join-Path $root "scripts\daily.py"
$taskName = "Futbol_ML - recoleccion diaria"

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$triggers = @(
    New-ScheduledTaskTrigger -Daily -At "10:00"   # resultados de ayer + cuotas tempranas
    New-ScheduledTaskTrigger -Daily -At "17:30"   # cuotas más cercanas al cierre de los partidos nocturnos
    New-ScheduledTaskTrigger -Daily -At "21:15"   # recién renovada la cuota de API-Football (00:00 UTC): cuotas tempranas
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
    -Description "Recolección (API-Football, football-data.co.uk), predicciones de seguimiento e informe (Futbol_ML)" -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State

# Cuota fresca y pronóstico final 1-2 h antes de cada partido (sale sin consultar la API si no hay partidos).
$preName = "Futbol_ML - cuotas pre-partido"
$preAction = New-ScheduledTaskAction -Execute $python -Argument "`"$(Join-Path $root "scripts\prekickoff.py")`"" `
    -WorkingDirectory $root
$preTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$preSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $preName -Action $preAction -Trigger $preTrigger -Settings $preSettings `
    -Description "Cuotas cercanas al inicio y pronóstico final (Futbol_ML)" -Force | Out-Null
Get-ScheduledTask -TaskName $preName | Select-Object TaskName, State
