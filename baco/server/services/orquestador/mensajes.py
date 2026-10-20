

MENSAJE_BIENVENIDA = (
    "Hola, soy Baco, agente encargado en asistirte en la carga de documentación "
    "a la base de conocimiento de Finnegans. ¿Sobre qué te gustaría publicar?"
)

OPCIONES_ENRIQUECER_DESCARTAR = ["enriquecer", "descartar"]
OPCIONES_ENRIQUECER_CONTINUAR = ["enriquecer", "continuar"]
OPCIONES_PLANTILLAS = ["instructivo", "soluciones"]
OPCIONES_REVISION_VALIDO = ["aprobar", "editar", "sanitizar", "rechazar", "reiniciar"]
OPCIONES_REVISION_BLOQUEANTE = ["editar", "sanitizar", "rechazar", "reiniciar"]
OPCIONES_REINICIAR = ["reiniciar"]

MSG_SIN_COINCIDENCIAS_TITULO = "No encontré coincidencias por título. Ingresá el texto del artículo."
MSG_DESCARTAR_COINCIDENCIA_TITULO = "Descartamos la coincidencia por título. Ingresá el texto del artículo."
MSG_ELEGIR_ENRIQUECER_O_DESCARTAR = "Elegí 'enriquecer' el artículo existente o 'descartar' para ingresar tu texto."
MSG_TEXTO_VACIO = "El texto no puede estar vacío. Ingresá el contenido del artículo."
MSG_ELEGIR_ENRIQUECER_O_CONTINUAR = "Elegí 'enriquecer' el artículo hallado o 'continuar' con tu propio texto."
MSG_ELEGIR_PLANTILLA = "Por favor, elegí el tipo de plantilla aplicable: 'instructivo' o 'soluciones'."
MSG_PEDIR_EDICION = "Enviá los campos que quieras modificar (titulo, texto, categoria_id o tags) para actualizar y re-validar el borrador."
MSG_RECHAZADO = "Borrador rechazado. No se realizaron cambios."

PREFIJO_SIN_DUPLICADOS = "Sin duplicados en el contenido. "
PREFIJO_CONTINUAR_PROPIO = "Continuamos con tu propio texto. "
PREFIJO_METADATOS_REGISTRADOS = "Metadatos registrados. "
PREFIJO_DATOS_SANITIZADOS = "Datos sensibles sanitizados. "
PREFIJO_BORRADOR_ACTUALIZADO = "Borrador actualizado. "
PREFIJO_ERROR_APROBACION = "No se puede aprobar mientras existan errores bloqueantes. "


def prefijo_borrador_creado(articulo_id: int) -> str:
    return f"Borrador de sesión creado sobre #{articulo_id}. "


def prefijo_borrador_enriquecido(articulo_id: int) -> str:
    return f"Borrador de enriquecimiento creado sobre #{articulo_id}. "


def msg_coincidencia(res_msg: str, titulo: str, url: str) -> str:
    return f"{res_msg} ({titulo} - {url})"


def msg_error_longitud_minima(campo: str, min_c: int) -> str:
    if campo == "texto":
        return f"El contenido del artículo debe tener al menos {min_c} caracteres."
    return f"Por favor, ingresá un {campo} descriptivo de al menos {min_c} caracteres."


def msg_error_longitud_maxima(campo: str, max_c: int) -> str:
    if campo == "texto":
        return f"El {campo} supera los {max_c} caracteres. Dividilo o resumilo para continuar."
    return f"El {campo} supera los {max_c} caracteres. Resumilo para continuar."


def msg_articulo_muy_largo(max_c: int) -> str:
    return (
        f"Este artículo es muy largo para editarlo desde el chat (supera los {max_c} caracteres). "
        "Podés modificarlo directamente en la plataforma."
    )


def msg_enriquecer_cargado(articulo_id: int, titulo: str) -> str:
    return (
        f"Seleccionaste enriquecer el artículo #{articulo_id} ('{titulo}'). "
        "Cargamos su contenido en tu editor para que puedas modificarlo, agregar información o corregirlo. "
        "Cuando termines, enviá el texto actualizado."
    )


def msg_pedir_plantilla(prefijo: str = "") -> str:
    return f"{prefijo}¿Qué tipo de plantilla corresponde aplicar a este artículo: 'instructivo' o 'soluciones'?"


def msg_pedir_metadatos(plantilla: str, prefijo: str = "") -> str:
    return (
        f"{prefijo}Plantilla '{plantilla}' seleccionada. "
        "Ingresá al menos un tag temático adicional (ej. 'ventas', 'facturacion', separados por coma si son varios) "
        "y opcionalmente el ID de categoría."
    )


def msg_pedir_tag_adicional(plantilla: str) -> str:
    return f"Ingresá al menos un tag temático adicional además de '{plantilla}' (ej. 'ventas', 'facturacion')."


def msg_articulo_aprobado(titulo: str) -> str:
    return f"Artículo '{titulo}' aprobado para publicación."


def msg_sesion_finalizada(estado_valor: str) -> str:
    return f"La sesión ya finalizó en estado {estado_valor}. Enviá 'reiniciar' para comenzar otra carga."
