import re
import unicodedata


#Para que lo que estoy comparando sea igual hay que usar regex, unicode por acentos o tildes, eliminar espacios vacios etc
def normalizar(string: str) -> str:
    titulo = string.lower()
    titulo = unicodedata.normalize('NFD', titulo)
    titulo= ''.join(c for c in titulo if unicodedata.category(c) != 'Mn')
    titulo = re.sub(r'[^\w\s]', '', titulo)
    titulo = re.sub(r'\s+', ' ', titulo).strip()
    return titulo
