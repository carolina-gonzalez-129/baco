from typing import Any, List, Optional, Tuple

from baco.server.schemas.chat_orquestado import EstadoFlujo


MENSAJE_BIENVENIDA = (
    "Hola, soy Baco. Te acompaño en todo el proceso para que tu artículo quede impecable "
    "en la base de conocimiento de Finnegans.\n\n"
    "¿Sobre qué tema tenés ganas de escribir hoy? "
    "Si todavía no tenés el título, no te preocupes: una buena guía es indicar la acción y el circuito, "
    'por ejemplo "Configurar facturación electrónica en Ventas".'
)

OPCIONES_ENRIQUECER_DESCARTAR = ["enriquecer", "descartar", "volver"]
OPCIONES_SERIE_DECISION = ["actualizar", "descartar", "volver"]
OPCIONES_ENRIQUECER_CONTINUAR = ["enriquecer", "continuar", "volver"]
OPCIONES_PLANTILLAS = ["instructivo", "soluciones", "volver"]
OPCIONES_REVISION_VALIDO = ["conforme", "editar", "rechazar"]
OPCIONES_REVISION_BLOQUEANTE = ["editar", "rechazar"]
OPCIONES_REINICIAR = ["reiniciar"]
OPCIONES_CONFORMIDAD = ["copiar_borrador", "reiniciar"]
OPCIONES_RECURSOS_SKILLS = ["quitar_recursos", "seguir_con_recursos", "volver"]

MSG_OPCIONES_RECURSOS_SKILLS = (
    "El texto ingresado contiene recursos multimedia (imágenes o enlaces a archivos). "
    "Las skills de asistencia de IA (aplicación de plantilla y auditoría semántica) solo admiten texto plano sin recursos.\n\n"
    "Podés elegir cómo querés continuar:\n"
    "- **Quitar recursos**: se retirarán las referencias multimedia para habilitar las skills de IA.\n"
    "- **Seguir con recursos**: conservarás las imágenes y adjuntos en el borrador, pero las skills quedarán deshabilitadas."
)

MSG_VOLVER_TITULO = (
    "Volvemos al paso anterior. Ingresá un nuevo título para tu artículo:"
)
MSG_VOLVER_TEXTO = (
    "Volvemos al paso anterior. Ingresá el texto corregido para tu artículo:"
)
MSG_VOLVER_TEXTO_ACTUALIZADO = (
    "Volvemos al paso anterior. Ingresá el texto actualizado para tu artículo:"
)
MSG_VOLVER_PLANTILLA = (
    "Volvemos a la selección de formato. ¿Qué plantilla preferís para este artículo?"
)
MSG_VOLVER_METADATOS = (
    "Volvemos al paso anterior. Podés redefinir las etiquetas o tags para clasificar tu artículo:"
)
MSG_VOLVER_ENRIQUECER_O_DESCARTAR = (
    "Volvemos al paso anterior. ¿Deseás enriquecer el artículo encontrado o descartarlo?"
)
MSG_OPERACION_CANCELADA = (
    "Operación cancelada. Mantenemos tu borrador intacto:\n\n"
)

MSG_SIN_COINCIDENCIAS_TITULO = (
    "No encontré nada similar. Por favor, enviame el texto o desarrollo del artículo."
)
MSG_DESCARTAR_COINCIDENCIA_TITULO = (
    "Descartamos la sugerencia para continuar con tu propuesta "
    "Por favor escribí o pegá el texto completo del artículo para continuar. Podes ir de a poco escribiendo desde aca"
    "y apretar 'Confirmar texto' cuando estes conforme, vas a ver el texto en el panel izquierdo"
)
MSG_ELEGIR_ENRIQUECER_O_DESCARTAR = (
    "Encontré un artículo existente sobre este tema. "
    "Tocá 'enriquecer' para trabajar sobre él y sumar tu aporte, "
    "o 'descartar' si tu caso es diferente y querés ingresar tu texto desde cero."
)
MSG_ELEGIR_SERIE_O_DESCARTAR = (
    "Este título pertenece a una serie periódica. "
    "Tocá 'actualizar' si querés renovar el contenido de la última entrega, "
    "o 'descartar' si se trata de una nueva edición que querés publicar por separado."
)
MSG_TEXTO_VACIO = (
    "Por favor, necesito que me pases el texto o los pasos del artículo "
    "para que podamos armarlo juntos. Pegalo o redactalo acá abajo cuando gustes."
)
MSG_TEXTO_EN_EDICION = (
    "Guardé tu texto en edición. Podés seguir escribiendo o pegando más contenido, "
    "y cuando esté listo tocá 'Confirmar texto' "
)
MSG_ELEGIR_ENRIQUECER_O_CONTINUAR = (
    "Detecté contenido muy parecido al que redactaste. "
    "Elegí 'enriquecer' si querés sumar tus cambios al documento actual, "
    "o 'continuar' si tu artículo trata un caso distinto."
)
MSG_ELEGIR_PLANTILLA = (
    "Definamos el formato: tocá 'instructivo' si es un paso a paso de configuración o uso, "
    "o 'soluciones' si describe la causa y resolución de un problema."
)
MSG_PEDIR_EDICION = (
    "Escribí el campo que querés ajustar junto con su nuevo valor "
    "(por ejemplo: titulo: Mi nuevo título o el texto actualizado) para actualizar el borrador."
)
MSG_RECHAZADO = (
    "Cancelamos el borrador y no se guardó ningún cambio. "
    "Si querés comenzar otra redacción desde el principio, tocá 'reiniciar'."
)
MSG_SESION_EXPIRADA = (
    "Disculpá la interrupción: la sesión se cerró por inactividad para proteger tus datos. "
    "Para retomar, ingresá el título de tu artículo o tocá 'reiniciar'."
)

PREFIJO_SIN_DUPLICADOS = "Sin duplicados en el contenido. "
PREFIJO_CONTINUAR_PROPIO = "Continuamos con tu propio texto. "
PREFIJO_METADATOS_REGISTRADOS = "Metadatos registrados. "
PREFIJO_DATOS_SANITIZADOS = "Datos sensibles sanitizados. "
PREFIJO_BORRADOR_ACTUALIZADO = "Borrador actualizado. "
PREFIJO_ERROR_CONFORMIDAD = "Todavía no podemos avanzar porque hay puntos obligatorios pendientes:\n"

MSG_ANTES_DE_CONFORME = (
    "Revisá el borrador. Si estás conforme con el contenido, tocá Estoy conforme. "
    "Esto registra tu conformidad; no lo publica."
)
MSG_CONFORMIDAD_REGISTRADA = (
    "✅ Registramos tu conformidad. Tu borrador pasó las validaciones mínimas y quedó listo. "
    "Todavía no está publicado: la aprobación y publicación final las hace un administrador. "
    "Podés copiar el borrador y cargarlo en la Base de Conocimiento."
)
MSG_CONFORMIDAD_INVALIDADA = (
    "Modificaste el borrador, así que necesito que vuelvas a confirmar tu conformidad."
)


def prefijo_borrador_creado(articulo_id: int) -> str:
    return f"Borrador de sesión creado sobre #{articulo_id}. "


def prefijo_borrador_enriquecido(articulo_id: int) -> str:
    return f"Borrador de enriquecimiento creado sobre #{articulo_id}. "


def msg_coincidencia(res_msg: str, titulo: str, url: str) -> str:
    return f"{res_msg} ({titulo} - {url})"


VARIANTES_TEXTO_VACIO = [
    "Perfecto, ahora necesito que me pases el texto o los pasos del artículo para que podamos armarlo juntos. Pegalo o redactalo acá abajo cuando gustes.",
    "El mensaje me llegó en blanco, probá pegando de nuevo el contenido acá.",
    "Aún no recibí el mensaje. Si necesitás prepararlo antes en tu editor, acá te espero; o podés tocar 'reiniciar' si preferís comenzar en otro momento.",
]


def msg_texto_vacio(intento: int = 0) -> str:
    return VARIANTES_TEXTO_VACIO[intento % len(VARIANTES_TEXTO_VACIO)]


VARIANTES_TITULO_CORTO = [
    "¡Me gusta la idea del tema! Para que a tus compañeros y clientes les sea bien fácil encontrarlo en el buscador, necesito que sea un poquito más largo (al menos 15 caracteres). ¿Cómo describirías la acción principal?",
    "Sé que a veces cuesta resumir en una sola frase, pero los títulos muy cortitos se pierden entre tantos artículos. Una fórmula que no falla es poner qué querés hacer y en qué pantalla o circuito (por ejemplo: la acción y el módulo).",
    "Tranqui, le encontramos la vuelta juntos. En lugar de poner solo una palabra como 'Ventas', probemos con algo como 'Configurar listas de precios en Ventas'. ¿Cómo te gustaría formular el tuyo?",
]


def msg_error_longitud_minima(campo: str, min_c: int, intento: int = 0) -> str:
    if campo == "texto":
        return f"El texto es demasiado corto para conformar un artículo útil. Necesito una explicación más detallada de al menos {min_c} caracteres."
    return VARIANTES_TITULO_CORTO[intento % len(VARIANTES_TITULO_CORTO)]


VARIANTES_TEXTO_LARGO = [
    "¡Se nota que le pusiste un montón de detalle y dedicación a la explicación! El texto supera los {max_c} caracteres permitidos para que a los usuarios no se les haga pesado de leer. ¿Te parece si dejamos los puntos esenciales acá o lo dividimos en dos entregas?",
    "Sé que da pereza tener que recortar cuando ya redactaste todo. Para no sobrecargar una única nota, una opción que suele funcionar re bien es publicar la guía básica ahora y armar un segundo artículo con los casos especiales. ¿Probamos acortarlo un poquito?",
]


def msg_error_longitud_maxima(campo: str, max_c: int, intento: int = 0) -> str:
    if campo == "texto":
        plantilla = VARIANTES_TEXTO_LARGO[intento % len(VARIANTES_TEXTO_LARGO)]
        return plantilla.format(max_c=max_c)
    return f"El título supera los {max_c} caracteres permitidos. Para que sea fácil de leer en la plataforma, resumí la idea principal e ingresalo de nuevo."


def msg_articulo_muy_largo(max_c: int) -> str:
    return (
        f"Este artículo es muy largo para editarlo desde el chat (supera los {max_c} caracteres). "
        "Podés modificarlo directamente en la plataforma. "
        "Tocá 'descartar' para escribir un texto nuevo o 'reiniciar' para volver al inicio."
    )


def msg_enriquecer_cargado(articulo_id: int, titulo: str) -> str:
    return (
        f"Cargué el texto del artículo #{articulo_id} ('{titulo}').\n\n"
        "Lo encontrás en la sección Vista Previa del panel izquierdo. "
        "Podés revisarlo, modificar explicaciones, eliminar secciones o adicionar nuevos pasos.\n\n"
        "Cuando termines tus cambios, enviame la versión completa para avanzar."
    )


def msg_actualizar_serie_cargado(articulo_id: int, titulo: str) -> str:
    return (
        f"Cargué el contenido de la última entrega de la serie (#{articulo_id} - '{titulo}').\n\n"
        "Lo encontrás en la sección Vista Previa del panel izquierdo. "
        "Tenés total libertad para trabajar sobre él: podés modificar lo que haya cambiado, "
        "eliminar los datos que ya no apliquen o adicionar las novedades.\n\n"
        "Cuando esté listo, enviame el texto completo actualizado."
    )


VARIANTES_OPCION_INVALIDA = [
    "Disculpá, no llegué a interpretar bien lo que me enviaste. Para que no tengas que escribirlo a mano, podés tocar directamente uno de los botones que te aparecen en pantalla.",
    "No te preocupes, a veces me confundo si no usamos la palabra exacta. Para que avancemos sobre seguro, elegí 'enriquecer' (o 'actualizar') si querés aprovechar lo que ya existe en la base, o 'descartar' si preferís ingresar tu contenido aparte.",
]


def msg_opcion_invalida(intento: int = 0) -> str:
    return VARIANTES_OPCION_INVALIDA[intento % len(VARIANTES_OPCION_INVALIDA)]


VARIANTES_TAGS_FALTANTES = [
    "¡Ya casi lo tenemos listo! Para que el artículo quede bien clasificado y cualquiera lo encuentre al toque en la plataforma, sumale al menos una etiqueta temática (por ejemplo: ventas, facturacion o stock).",
    "No te preocupes si no estás seguro de cuál usar. Pensá en qué palabra escribirías vos en el buscador si tuvieras este problema en el trabajo (el módulo o el circuito). Con una o dos palabras clave separadas por coma ya estamos.",
]


VARIANTES_CATEGORIA_FALTANTE = [
    "¡Perfecto! Ya asignamos las etiquetas temáticas. Ahora por favor decime la categoría por acá si ya sabés cuál es (por ejemplo: Ventas, Compras). Si no sabés cuál es, podés buscarla y seleccionarla desde el menú desplegable en la sección inferior del panel izquierdo.",
    "Falta definir la categoría: podés escribirla por acá si ya la sabés (ej. Ventas, Compras) o seleccionarla desde el menú desplegable en la sección inferior del panel izquierdo.",
]


def msg_pedir_categoria(intento: int = 0) -> str:
    return VARIANTES_CATEGORIA_FALTANTE[intento % len(VARIANTES_CATEGORIA_FALTANTE)]


def msg_categoria_no_encontrada(termino: str, sugerencias: Optional[List[str]] = None) -> str:
    sug_txt = ""
    if sugerencias:
        if len(sugerencias) == 1:
            sug_txt = f" (por ejemplo: {sugerencias[0]})"
        else:
            sug_txt = f" (por ejemplo: {', '.join(sugerencias[:3])})"
    return (
        f"No encontré la categoría '{termino}'. Podés seleccionarla desde el menú desplegable en la sección inferior del panel izquierdo o probar escribiendo una categoría válida{sug_txt}."
    )


def msg_categoria_ambigua(termino: str, candidatos: List[str]) -> str:
    if not candidatos:
        return f"Encontré coincidencias ambiguas para '{termino}'. Por favor seleccioná la categoría desde el menú desplegable en la sección inferior del panel izquierdo."
    if len(candidatos) == 1:
        return f"¿Te referís a la categoría '{candidatos[0]}'? Podés confirmarla o elegirla desde el menú desplegable en la sección inferior del panel izquierdo."
    if len(candidatos) == 2:
        cands_txt = f"{candidatos[0]} o {candidatos[1]}"
    else:
        cands_txt = f"{', '.join(candidatos[:-1])} o {candidatos[-1]}"
    return (
        f"Encontré varias categorías que coinciden con '{termino}': ¿te referís a {cands_txt}? También podés seleccionarla desde el menú desplegable en la sección inferior del panel izquierdo."
    )


def msg_pedir_tags_y_categoria(plantilla: str = "", intento: int = 0) -> str:
    art = f"el {plantilla}" if plantilla else "el artículo"
    return (
        f"Necesitamos al menos dos etiquetas temáticas para clasificar {art} "
        "y que selecciones la categoría desde el menú desplegable en el formulario de la izquierda."
    )


def msg_pedir_tag_adicional(plantilla: str = "", intento: int = 0) -> str:
    return VARIANTES_TAGS_FALTANTES[intento % len(VARIANTES_TAGS_FALTANTES)]


def msg_pedir_plantilla(prefijo: str = "") -> str:
    return f"{prefijo}{MSG_ELEGIR_PLANTILLA}"


def msg_pedir_metadatos(plantilla: str, prefijo: str = "") -> str:
    return (
        f"{prefijo}Asignamos el formato '{plantilla}'. "
        "Para clasificar el artículo, por favor ingresá 2 etiquetas temáticas por acá si ya sabés cuáles son. "
        "Si no sabés cuáles son, podés buscarlas e ingresarlas desde la sección inferior del panel izquierdo."
    )


def msg_articulo_conforme(titulo: str = "") -> str:
    return MSG_CONFORMIDAD_REGISTRADA


def msg_sesion_finalizada(estado_valor: str) -> str:
    return f"Esta conversación ya concluyó (el artículo fue {estado_valor}). Para comenzar una nueva redacción, tocá 'reiniciar'."


def obtener_ayuda_contextual(sesion: Any) -> Tuple[str, List[str]]:
    est = sesion.estado
    if est == EstadoFlujo.ESPERANDO_TITULO:
        return (
            "Estás en el inicio de la redacción. Por favor, ingresá el título de tu artículo (por ejemplo: la acción y el circuito).",
            [],
        )
    if est == EstadoFlujo.DECISION_TITULO:
        es_serie = bool(sesion.coincidencias and sesion.coincidencias[0].tipo_coincidencia == "serie")
        ops = OPCIONES_SERIE_DECISION if es_serie else OPCIONES_ENRIQUECER_DESCARTAR
        return (
            " Encontré un artículo similar en la base. Podés enriquecerlo/actualizarlo, descartarlo para escribir uno nuevo con este título, o tocar 'volver' para ingresar otro título.",
            list(ops),
        )
    if est == EstadoFlujo.ESPERANDO_TEXTO:
        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            return (
                "  Cargamos el artículo existente. Podés editarlo o sumar contenido nuevo desde el panel izquierdo. También podés tocar 'descartar' si preferís escribir tu propio texto desde cero, o 'volver'.",
                ["confirmar_texto", "descartar", "volver"],
            )
        return (
            "  Necesito el texto o los pasos de tu artículo (al menos 20 caracteres). Pegalo o redactalo acá abajo cuando gustes, o tocá 'volver' para cambiar el título.",
            ["confirmar_texto", "volver"],
        )
    if est == EstadoFlujo.DECISION_TEXTO:
        return (
            "  Encontré un artículo con contenido muy parecido. Podés elegir 'enriquecer' para sumar tu aporte, 'continuar' para publicar tu texto propio, o 'volver' para modificar tu texto.",
            list(OPCIONES_ENRIQUECER_CONTINUAR),
        )
    if est == EstadoFlujo.ESPERANDO_PLANTILLA:
        return (
            "  Seleccioná la plantilla que mejor se ajuste a tu documento ('instructivo' o 'soluciones'), o tocá 'volver' para revisar el texto.",
            list(OPCIONES_PLANTILLAS),
        )
    if est == EstadoFlujo.ESPERANDO_METADATOS:
        plantilla = (sesion.borrador.tipo_plantilla if sesion.borrador else "") or ""
        return (
            f" Necesitamos al menos dos etiquetas temáticas para clasificar el {plantilla} "
            "y que selecciones la categoría desde el menú desplegable en el formulario de la izquierda. "
            "Podés escribir las etiquetas acá o tocar 'volver' para cambiar de plantilla.",
            ["volver"],
        )
    if est in (EstadoFlujo.REVISION_BORRADOR, EstadoFlujo.SUBSANANDO_BORRADOR):
        if getattr(sesion, "confirmando_rechazo", False):
            return (
                " Estás por descartar el borrador. Tocá 'confirmar_rechazo' si querés cancelarlo definitivamente, o 'volver' para conservarlo.",
                ["confirmar_rechazo", "volver"],
            )
        if sesion.validacion and not sesion.validacion.valido:
            return (
                "El borrador tiene puntos pendientes obligatorios. Podés tocar 'editar' para corregirlos o 'rechazar' para cancelar.",
                list(OPCIONES_REVISION_BLOQUEANTE),
            )
        return (
            " El borrador está listo para confirmar. Podés tocar 'conforme' para registrar tu conformidad, 'editar' para cambiar algún campo, o 'rechazar' para cancelar.",
            list(OPCIONES_REVISION_VALIDO),
        )
    if est in (EstadoFlujo.CONFORMIDAD_USUARIO, EstadoFlujo.RECHAZADO):
        return (
            msg_sesion_finalizada(est.value),
            OPCIONES_REINICIAR,
        )
    return (
        " Podes continuar escribiendo o tocar 'reiniciar' para comenzar de nuevo.",
        OPCIONES_REINICIAR,
    )
