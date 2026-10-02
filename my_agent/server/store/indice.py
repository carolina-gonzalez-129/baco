#Indice en emoria de la base de conocimiento : Se construye una vez desde Discourse
#denberia guardarla en discor asi no se reconstruye cada vez q arranca el servidor
#ES MUY IMPORTANTE QUE DESPUES HAGA ESO!
#Va a contener articulo_por_slug : {slug:{id,titulo,url}} (slug es el titulo normalizado usando slugify)
# hashes: {hash_de_la_descripcion:id}
# y matriz de embedings
#el id une todas las estructuras

from my_agent.server.discourse import client
import hashlib
import time

import httpx
import numpy as np
from bs4 import BeautifulSoup
from slugify import slugify
from sentence_transformers import SentenceTransformer
