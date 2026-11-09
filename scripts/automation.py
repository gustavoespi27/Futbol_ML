"""Estado y pausa con expiración: automation.py status | pausa 2h | reanudar."""

import argparse
import json
import re
import subprocess

from footy_agents import automation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "pausa", "reanudar"])
    parser.add_argument("duration", nargs="?", default="2h")
    args = parser.parse_args()
    if args.action == "pausa":
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([hm])", args.duration)
        if not match or float(match[1]) <= 0:
            parser.error("Duración positiva con h o m, por ejemplo 2h o 30m")
        automation.pause(float(match[1]) * (3600 if match[2] == "h" else 60))
    elif args.action == "reanudar":
        automation.write_state("control", {})
    status = {"pausa_vigente": automation.paused(), "control": automation.read_state("control"),
              "daily": automation.read_state("daily"), "prekickoff": automation.read_state("prekickoff")}
    if automation.os.name == "nt":
        command = ("Get-ScheduledTask | Where-Object TaskName -like 'Futbol_ML*' | ForEach-Object { "
                   "$taskInfo = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{ tarea=$_.TaskName; "
                   "estado=[string]$_.State; ultima=$taskInfo.LastRunTime.ToUniversalTime().ToString('o'); "
                   "proxima=$taskInfo.NextRunTime.ToUniversalTime().ToString('o') } } | "
                   "ConvertTo-Json -Compress")
        try:
            status["programador"] = json.loads(subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", command], text=True, timeout=10))
        except (OSError, subprocess.SubprocessError, ValueError):
            status["programador"] = "No se pudo consultar el Programador de tareas"
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
