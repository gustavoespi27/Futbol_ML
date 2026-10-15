"""Levanta el dashboard en http://127.0.0.1:8000 y lo abre en el navegador. Escucha en todas las interfaces, así que
también se abre desde el teléfono en la misma red WiFi (la URL se muestra al iniciar).

Uso:  python scripts/serve.py [--host 0.0.0.0] [--port 8000] [--no-browser]
      --host 127.0.0.1 lo deja solo para este equipo.
"""

import argparse
import socket
import threading
import webbrowser

import uvicorn


def get_local_ip() -> str:
    """IP de este equipo en la red local: la de la interfaz por la que saldría el tráfico (UDP no envía nada)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"Dashboard local:   {url}")
    if args.host != "127.0.0.1":
        print(f"Acceso móvil/WiFi: http://{get_local_ip()}:{args.port}")
    print("(Ctrl+C para detener)")
    uvicorn.run("footy.web.app:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
