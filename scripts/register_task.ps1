# Registra (o actualiza) la tarea programada de recolección diaria.
# Corre 2 veces al día; si el PC estaba apagado, se ejecuta al encenderlo (StartWhenAvailable).
# Uso: powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\collect_daily.py"
$taskName = "Footbol_ML - recoleccion diaria"

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$triggers = @(
    New-ScheduledTaskTrigger -Daily -At "10:00"   # resultados de ayer + cuotas tempranas
    New-ScheduledTaskTrigger -Daily -At "17:30"   # cuotas más cercanas al cierre de los partidos nocturnos
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
    -Description "Descarga calendario, cuotas y detalles desde API-Football (Footbol_ML)" -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
