import sys
from pathlib import Path
import json
#SOLO NORMALIZA TITULOS!
#IMPORTANTE : esto voy a tener q tenerlo en varios mas, revisar toods xq sino da module error
#Xq no reconoce a my_agent
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from my_agent.server.services.normalizar import normalizar
from dotenv import load_dotenv
import os

load_dotenv()

RUTA_ARTICULOS_JSON= os.getenv("RUTA_ARTICULOS_JSON")
RUTA_ARTICULOS_NORMALIZADOS_JSON= os.getenv("RUTA_ARTICULOS_NORMALIZADOS_JSON")

def cargar_articulos(ruta_json: str) -> list[dict]:
    with open(ruta_json, encoding="utf-8") as f:
        datos = json.load(f)
    return datos if isinstance(datos, list) else next(
        v for v in datos.values() if isinstance(v, list)
    )


def normalizar_articulos(ruta_json: str) -> dict[int, str]:
    """Devuelve {id_del_articulo: titulo_normalizado}"""
    return {
        a["id"]: normalizar(a.get("titulo") or "")
        for a in cargar_articulos(ruta_json)
    }


def guardar(normalizados: dict[int, str], ruta_salida: str) -> None:
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(normalizados, f, ensure_ascii=False, separators=(",", ":"))


def cargar_normalizados(ruta: str) -> dict[int, str]:
    """JSON guarda las claves como string, acá se vuelven a int."""
    with open(ruta, encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


if __name__ == "__main__":
    normalizados = normalizar_articulos(RUTA_ARTICULOS_JSON)

    assert all(normalizados.values()), "Hay títulos vacíos tras normalizar"

    guardar(normalizados, RUTA_ARTICULOS_NORMALIZADOS_JSON)
    print(f"{len(normalizados)} artículos normalizados")