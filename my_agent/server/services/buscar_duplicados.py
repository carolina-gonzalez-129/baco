import json
import sys
from contextlib import nullcontext
from pathlib import Path
#IMPORTANTE : esto voy a tener q tenerlo en varios mas, revisar toods xq sino da module error
#Xq no reconoce a my_agent, creo q si no se ejecutan deberia borrarlo
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from my_agent.server.discourse import client
from my_agent.server.services.normalizar import normalizar
from rapidfuzz import fuzz
import hashlib
from dotenv import load_dotenv
import os
import numpy as np
from rapidfuzz import process, fuzz
load_dotenv()
#Cargo la ruta de los articulos normalizados y los convierto a un  dict de python
#Un dict es implicitamente un hash donde la key es el id y el value el titulo


articulos_normalizados_path = os.getenv("RUTA_ARTICULOS_NORMALIZADOS_JSON")

#creo el dict
with open(articulos_normalizados_path, "r", encoding="utf-8") as f:
    articulos_normalizados_dict = json.load(f)

### Uso rapidfuzz xq es una libreria super rapida q usa c y me permite obtener rpetidos
def buscar_por_titulo_rapidfuzz(string:str):
    #normalizo el titulo que recibo
    titulo_normalizado = normalizar(string)
    #scorer recalibrar cual podria ser el mejor, extractOne itera y busca el q mejor se alinea
    #LOS THRESHOLDS TENDRIA QUE DESPUES RECALIBRARLOS CUANDO ANTIGRAVITY PROCESE LAS 6000 ENTRADAS
    match = process.extractOne(titulo_normalizado,articulos_normalizados_dict,scorer=fuzz.WRatio,score_cutoff=80)
    #match retorna una tupla, pero yo voy a querer dsps quedarme solo con el id para q dsps sea facil
    #pasarle al server el id y q haga get/id para mostrarselo al user (lo linkearia con la url)
    return match[2] if match else None

def buscar_por_descripcion(string:str):
#aca si lo de embeddings, estaria bueno ya guardarlo en disco tmb xq sino es mas pesado generarlo
 descripcion_normalizada=normalizar(string)
#creo el embedding generando un dict de descripciones
#TENDRIA QUE NORMALIZARLOS TMB EN LA DESCRIPCION
#Ellos los llaman texto asique voy a respetar eso



