@echo off
REM Abre el dashboard de Futbol_ML en http://127.0.0.1:8000 (cerrar esta ventana lo detiene)
cd /d "%~dp0"
".venv\Scripts\python.exe" scripts\serve.py
pause
