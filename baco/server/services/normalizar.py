import hashlib
import re
import unicodedata


# Para que lo que estoy comparando sea igual hay que usar regex, unicode por acentos o tildes, eliminar espacios vacios etc
def normalizar(string: str) -> str:
    if not string:
        return ""
    titulo = string.lower()
    titulo = unicodedata.normalize('NFD', titulo)
    titulo = ''.join(c for c in titulo if unicodedata.category(c) != 'Mn')
    titulo = re.sub(r'[^\w\s]|_', ' ', titulo)
    titulo = re.sub(r'\s+', ' ', titulo).strip()
    return titulo


def calcular_hash(texto: str | None) -> str | None:
    """Calcula el hash MD5 del texto normalizado según la regla oficial del proyecto.

    Recibe el texto original, aplica normalizar(), luego .encode('utf-8')
    y hashlib.md5(...).hexdigest().
    Si el texto es None o queda vacío / sin contenido alfanumérico tras normalizar,
    devuelve None (nunca el hash de la cadena vacía).
    """
    if texto is None:
        return None
    texto_norm = normalizar(texto)
    if not texto_norm or not any(c.isalnum() for c in texto_norm):
        return None
    return hashlib.md5(texto_norm.encode("utf-8")).hexdigest()
