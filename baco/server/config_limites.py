TITULO_MIN = 15  # Alineado con Discourse
TITULO_MAX = 255  # El percentil 99 igual tiene 176, pero es para alinearse con Discourse
TEXTO_MIN = 20    # Alineado con Discourse
TEXTO_MAX = 6687  # Percentil 95 del largo de texto en la tabla de artículos (Octubre 2026)
TAGS_MIN = 2      # min de etiquetas requeridas por artículo
TAGS_MAX = 5      # limite habitual permitido en discourse
TAGS_PLANTILLAS_PERMITIDAS = ("instructivo", "soluciones")

#AGREGAR UN MENU DESPLEGABLE PARA QUE SI NO SE PUDO INFERIR SE PUEDA SELECCIONAR VIENDOLAS X NOMBRE!
CATEGORIA_ID_DEFAULT = 1

# Configuración de Recursos Multimedia en Sesión
PERMITIR_SUBIDA_RECURSOS: bool = True  # Habilitado: el mini panel permite subir archivos al borrador
RECURSO_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB máximo por recurso
MAX_RECURSOS_TOTAL_BYTES: int = 50 * 1024 * 1024  # 50 MB máximo total de recursos acumulados
MAX_RECURSOS_POR_SESION: int = 20  # Límite de recursos por borrador de sesión
