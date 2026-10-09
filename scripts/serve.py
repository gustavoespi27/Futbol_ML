"""Levanta el dashboard en http://127.0.0.1:8000 y lo abre en el navegador.

Uso:  python scripts/serve.py [--port 8000] [--no-browser]
"""

import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"Dashboard en {url}  (Ctrl+C para detener)")
    uvicorn.run("footy.web.app:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
