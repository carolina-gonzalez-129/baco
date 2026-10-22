#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import httpx
from baco.server.app.middleware import API_KEY


def main():
    parser = argparse.ArgumentParser(description="Cliente interactivo mínimo de BACO")
    parser.add_argument(
        "--url",
        default=os.getenv("BACO_URL") or os.getenv("CLOUDFLARE_TUNNEL_URL") or "http://127.0.0.1:8080",
        help="URL base del servidor (default: http://127.0.0.1:8080)",
    )
    args = parser.parse_args()

    base_url = args.url.replace("://0.0.0.0", "://127.0.0.1").rstrip("/")
    api_key = API_KEY or os.getenv("API_KEY_SERVIDOR", "")

    client = httpx.Client(
        base_url=base_url,
        headers={"X-API-Key": api_key},
        timeout=60.0,
    )

    print(f"Conectando al Orquestador en: {base_url}/chat")

    res = client.post("/chat", json={})
    if res.status_code != 200:
        print(f"\n[ERROR DE CONEXIÓN {res.status_code}]: {res.text}")
        return

    resp = res.json()
    session_id = resp.get("session_id")

    while True:
        estado = resp.get("estado")
        mensaje = resp.get("mensaje", "")
        opciones = resp.get("opciones") or []
        aviso_priv = resp.get("aviso_privacidad")

        print(f"\n[Estado: {estado}]")
        if aviso_priv:
            print(f"Aviso de privacidad: {aviso_priv}")
        print(f"{mensaje}")
        if opciones:
            print(f"Opciones: {opciones}")

        if estado in ("APROBADO", "RECHAZADO"):
            break

        entrada = input("\n> ").strip()

        if entrada.lower() in ("ayuda", "?"):
            payload = {"mensaje": "ayuda"}
        elif entrada.lower() in ("volver", "atras"):
            payload = {"accion": "volver"}
        elif entrada.lower() == "reiniciar":
            payload = {"accion": "reiniciar"}

        elif estado == "ESPERANDO_TITULO":
            payload = {"titulo": entrada}

        elif estado == "ESPERANDO_TEXTO":
            if entrada.lower() in ("descartar", "continuar"):
                payload = {"accion": entrada.lower()}
            else:
                payload = {"texto": entrada}

        elif estado == "ESPERANDO_METADATOS":
            payload = {"mensaje": entrada}

        elif estado in ("REVISION_BORRADOR", "SUBSANANDO_BORRADOR") and entrada.lower() in ("editar", "corregir"):
            campo = input("Campo a editar [titulo / texto / tags]: ").strip().lower()
            nuevo_val = input(f"Nuevo valor para {campo}: ").strip()
            if campo == "tags":
                payload = {"accion": "editar", "tags": [t.strip() for t in nuevo_val.split(",") if t.strip()]}
            else:
                payload = {"accion": "editar", campo: nuevo_val}

        else:
            payload = {"accion": entrada}

        headers = {"X-Session-ID": session_id} if session_id else {}
        res = client.post("/chat", json=payload, headers=headers)
        if res.status_code != 200:
            print(f"\n[ERROR HTTP {res.status_code}]: {res.text}")
            break

        resp = res.json()
        session_id = resp.get("session_id", session_id)


if __name__ == "__main__":
    main()
