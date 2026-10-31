"""
Prueba manual del paso 1: POST /chat/revalidar-post-skill (v3)

Cambios respecto de v2:
  - Un httpx.Client NUEVO por caso: antes la cookie baco_session viajaba entre casos
    y el servidor reutilizaba la sesión del caso 1.
  - Después de confirmar el texto, avanza los turnos del chat hasta llegar a
    CONFORMIDAD_USUARIO (el endpoint nuevo solo acepta ese estado), mirando el
    "estado" y las "opciones" de cada respuesta.

Uso (PowerShell):
    $env:BACO_URL = "http://localhost:8001"
    $env:API_KEY = "tu_api_key"
    python probar_revalidacion_v3.py

Si el avance se detiene en un estado que no conozco, el script lo imprime:
copiá el Payload real de ese turno desde DevTools y ajustá payload_para().
"""
import json
import os

import httpx

BASE_URL = os.getenv("BACO_URL", "http://localhost:8081")
API_KEY = os.getenv("API_KEY", "Ojalaaprobemos123")

TITULO = "Eliminar el overselling en picos de demanda usando bloqueos pesimistas"
CATEGORIA_ID = 20          # "Ventas" (existe en categorias_disponibles)
TAGS = ["ventas", "stock"]  # existen en tags_disponibles
MAX_TURNOS = 8

CASOS = [
    {
        "nombre": "1. Texto sano",
        "texto": (
            "## Objetivo\nExplicar cómo evitar la venta de stock inexistente.\n\n"
            "## Pasos\n1. Abrir la transacción.\n2. Bloquear la fila de stock.\n"
            "3. Confirmar la venta y liberar el bloqueo.\n"
        ),
        "estado_esperado": "ok",
    },
    {
        "nombre": "2. Título repetido como primera línea",
        "texto": (
            f"# {TITULO}\n\n## Objetivo\nExplicar cómo evitar la venta de stock inexistente.\n\n"
            "## Pasos\n1. Abrir la transacción.\n2. Bloquear la fila de stock.\n"
        ),
        "estado_esperado": "ok",
    },
    {
        "nombre": "3. Texto con PII (DNI y mail)",
        "texto": (
            "## Objetivo\nContactar al cliente con DNI 30.123.456 "
            "o al mail juan.perez@example.com para validar el acceso.\n\n"
            "## Pasos\n1. Abrir la transacción.\n2. Bloquear la fila de stock.\n"
        ),
        "estado_esperado": "ok",
    },
    {
        "nombre": "4. Texto fuera de cota (demasiado largo)",
        "texto": "## Objetivo\n" + ("Texto de relleno para superar la cota. " * 300),
        "estado_esperado": "requiere_accion",
    },
]


def resumen(data):
    if not isinstance(data, dict):
        return data
    claves = ("estado", "mensaje", "opciones", "texto_limpio", "validacion")
    return {k: data.get(k) for k in claves if k in data}


class Sesion:
    def __init__(self):
        # Client nuevo = cookies nuevas = sesión nueva.
        self.client = httpx.Client(base_url=BASE_URL, timeout=60)
        self.sid = None

    def post(self, path, cuerpo=None):
        h = {}
        if API_KEY:
            h["X-API-Key"] = API_KEY
        if self.sid:
            h["X-Session-ID"] = self.sid
        r = self.client.post(path, headers=h, json=cuerpo if cuerpo is not None else {})
        nuevo = r.headers.get("X-Session-ID")
        if nuevo:
            self.sid = nuevo
        return r

    def cerrar(self):
        self.client.close()


def mostrar(titulo, r):
    print(f"--- {titulo}: HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        print(r.text)
        return None
    print(json.dumps(resumen(data), indent=2, ensure_ascii=False))
    return data


def payload_para(data):
    """Decide el siguiente turno según estado y opciones. Mejor suposición: ajustar si falla."""
    estado = (data.get("estado") or "").upper()
    opciones = data.get("opciones") or []

    if "instructivo" in opciones:
        return {"accion": "instructivo"}
    if "CATEGORIA" in estado or "ETIQUETA" in estado or "TAG" in estado:
        return {"categoria_id": CATEGORIA_ID, "tags": TAGS}
    for op in opciones:
        if "conforme" in op.lower():
            return {"accion": op}
    for op in opciones:
        if op.lower() in ("continuar", "confirmar", "siguiente"):
            return {"accion": op}
    return None


def sembrar_borrador(s, texto):
    r1 = s.post("/chat", {"titulo": TITULO})
    d1 = mostrar("turno título", r1)
    if r1.status_code != 200 or not d1 or d1.get("estado") != "ESPERANDO_TEXTO":
        print("!! El chat no pidió el texto.")
        return False

    r2 = s.post("/chat", {"texto": texto, "accion": "confirmar_texto"})
    data = mostrar("turno texto + confirmar", r2)
    if r2.status_code != 200 or not data:
        return False

    for i in range(MAX_TURNOS):
        if data.get("estado") == "CONFORMIDAD_USUARIO":
            return True
        payload = payload_para(data)
        if payload is None:
            print(f"!! No sé cómo avanzar desde el estado {data.get('estado')!r}.")
            print("   Copiá el Payload real de ese turno (DevTools) y ajustá payload_para().")
            return False
        r = s.post("/chat", payload)
        data = mostrar(f"avance {i + 1} {payload}", r)
        if r.status_code != 200 or not data:
            return False
    return data.get("estado") == "CONFORMIDAD_USUARIO"


def main():
    for caso in CASOS:
        print("=" * 70)
        print(caso["nombre"])
        s = Sesion()
        try:
            if not sembrar_borrador(s, caso["texto"]):
                print("[SALTEADO] no se pudo llegar a CONFORMIDAD_USUARIO")
                continue
            r = s.post("/chat/revalidar-post-skill")
            print(f"--- revalidar-post-skill: HTTP {r.status_code}")
            try:
                data = r.json()
            except ValueError:
                print(r.text)
                continue
            print(json.dumps(data, indent=2, ensure_ascii=False))
            estado = data.get("estado") if isinstance(data, dict) else None
            marca = "OK" if estado == caso["estado_esperado"] else "REVISAR"
            print(f"[{marca}] estado={estado!r} esperado={caso['estado_esperado']!r}")
        finally:
            s.cerrar()


if __name__ == "__main__":
    main()