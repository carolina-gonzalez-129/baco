
#Indice en memoria de la base de conocimiento : Se construye una vez desde Discourse
#denberia guardarla en disco asi no se reconstruye cada vez q arranca el servidor
#ES MUY IMPORTANTE QUE DESPUES HAGA ESO!

 #Aca tendria

from my_agent.server.discourse import client
import hashlib
import time

import httpx
import numpy as np
from bs4 import BeautifulSoup
from slugify import slugify
from sentence_transformers import SentenceTransformer
