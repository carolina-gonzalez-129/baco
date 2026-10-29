from typing import Any, List, Optional, Tuple

from baco.server.schemas.chat_orquestado import EstadoFlujo


MENSAJE_BIENVENIDA = (
    "🤖 ¡Hola! Soy BACO, tu asistente en la Base de Conocimiento de Finnegans.\n\n"
    "Para comenzar, **escribí el título** de lo que te gustaría publicar. "
    "Una buena fórmula es incluir la acción y el módulo (por ejemplo: *Configurar punto de venta en Ventas*).\n\n"
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
    " El texto ingresado contiene recursos multimedia (imágenes o enlaces a archivos). "
    "Las skills de asistencia de IA (aplicación de plantilla y auditoría semántica) solo admiten texto plano sin recursos.\n\n"
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
    "✨ Seguimos con tu propuesta de artículo.\n\n"
    "Escribí o pegá el contenido acá abajo y tocá **Confirmar texto** cuando esté listo."
)
MSG_ELEGIR_ENRIQUECER_O_DESCARTAR = (
    "📄 Ya existe un artículo que habla sobre este tema.\n\n"
    "¿Querés enriquecer el existente o es un tema distinto?"
)
MSG_ELEGIR_SERIE_O_DESCARTAR = (
    "📚 Encontré una serie periódica sobre este tema.\n\n"
    "¿Querés actualizar la última entrega o es un tema distinto?"
)
MSG_TEXTO_VACIO = (
    "Por favor, necesito que me pases el texto o los pasos del artículo "
    "para que podamos armarlo juntos. Pegalo o redactalo acá abajo cuando gustes."
)
MSG_TEXTO_EN_EDICION = (
    "📝 Guardé tu texto en el editor.\n\n"
    "Podés seguir escribiendo o pegando más contenido, y cuando esté listo tocá **Confirmar texto**."
)
MSG_ELEGIR_ENRIQUECER_O_CONTINUAR = (
    "🔍 Encontré un artículo con contenido muy similar.\n\n"
    "Podés **Enriquecer el existente** para sumar tu aporte, "
    "o elegir **Continuar con mi texto** si tu caso es diferente."
)
MSG_ELEGIR_PLANTILLA = (
    "📋 Elegí el formato para tu artículo:\n\n"
    "Tocá **Instructivo** si es un paso a paso, o **Soluciones** si resuelve un error o consulta."
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

PREFIJO_SIN_DUPLICADOS = " "
PREFIJO_CONTINUAR_PROPIO = " "
PREFIJO_METADATOS_REGISTRADOS = " "
PREFIJO_DATOS_SANITIZADOS = ". "
PREFIJO_BORRADOR_ACTUALIZADO = " "
PREFIJO_ERROR_CONFORMIDAD = "Todavía no podemos avanzar porque hay puntos obligatorios pendientes:\n"

MSG_ANTES_DE_CONFORME = (
    "Revisá el borrador. Si estás conforme con el contenido, tocá **Estoy conforme**."
)
MSG_CONFORMIDAD_REGISTRADA = (
    "✅ Genial! Registramos tu conformidad. Tu borrador pasó las validaciones mínimas y quedo listo. "
    "Todavía no esta publicado: la aprobación y publicación final las hace un moderador. "
)
MSG_CONFORMIDAD_INVALIDADA = (
    "Modificaste el borrador, así que necesito que vuelvas a confirmar tu conformidad."
)


def prefijo_borrador_creado(articulo_id: int) -> str:
    return ""


def prefijo_borrador_enriquecido(articulo_id: int) -> str:
    return ""


def msg_coincidencia(res_msg: str, titulo: str, url: str) -> str:
    return f"{res_msg} ({titulo} - {url})"


VARIANTES_TEXTO_VACIO = [
    "Necesito que me pases el texto o los pasos del artículo para que podamos armarlo juntos. Pegalo o redactalo acá abajo cuando gustes.",
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
        "Tocá 'descartar' para escribir un texto nuevo o 'reiniciar' para volver al inicio."
    )


def msg_enriquecer_cargado(articulo_id: int, titulo: str) -> str:
    return (
        f"📄 Cargué el artículo ('{titulo}') en la **Vista previa** del panel izquierdo.\n\n"
        "Hace los cambios que necesites y tocá **Confirmar texto**."
    )


def msg_actualizar_serie_cargado(articulo_id: int, titulo: str) -> str:
    return (
        f'📄 Cargué la ultima publicación de la serie ("{titulo}") en la **Vista previa** del panel izquierdo.\n\n'
        "Hace los cambios que necesites y tocá **Confirmar texto**."
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
    "¡Etiquetas listas! Ahora indicame la **categoría** por acá o seleccionala en el menú de  **panel izquierdo** y tocá **Enviar datos**.",
    "Sólo falta la **categoría**: escribila por acá (ej: Ventas) o elegila en el **panel izquierdo** y tocá **Enviar datos**.",
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
        f"Necesitamos al menos dos etiquetas para clasificar {art} "
        "y que selecciones la categoría ."
    )


def msg_pedir_tag_adicional(plantilla: str = "", intento: int = 0) -> str:
    return VARIANTES_TAGS_FALTANTES[intento % len(VARIANTES_TAGS_FALTANTES)]


def msg_pedir_plantilla(prefijo: str = "") -> str:
    return f"{prefijo}{MSG_ELEGIR_PLANTILLA}"


def msg_pedir_metadatos(plantilla: str, prefijo: str = "") -> str:
    return (
        f"{prefijo}🏷️ Asignamos el formato **{plantilla.capitalize()}**.\n\n"
        "Para continuar, completá la clasificación:\n"
        "• Sumá **al menos una etiqueta más** (o las que creas necesarias).\n"
        "Podés indicarlas por aca o cargarlas en el menu desplegable arriba del panel izquierdo."
    )


def msg_articulo_conforme(titulo: str = "") -> str:
    return MSG_CONFORMIDAD_REGISTRADA


def msg_sesion_finalizada(estado_valor: str) -> str:
    return f"Esta conversación ya concluyó (el artículo fue {estado_valor}). Para comenzar una nueva redacción, tocá 'reiniciar'."


def obtener_ayuda_contextual(sesion: Any) -> Tuple[str, List[str]]:
    est = sesion.estado


    if est == EstadoFlujo.ESPERANDO_TITULO:
        return (
            "📝 Escribí el título de tu artículo para comenzar (mínimo 15 caracteres, por ejemplo la acción y el módulo).",
            [],
        )

    if est == EstadoFlujo.DECISION_TITULO:
        es_serie = bool(sesion.coincidencias and sesion.coincidencias[0].tipo_coincidencia == "serie")
        if es_serie:
            msg = (
                "📚 Encontré una serie periódica con este título.\n\n"
                "Podés **Actualizar el existente** para sumar una nueva entrega, "
                "elegir **Es un tema distinto** o **Volver**."
            )
            return msg, list(OPCIONES_SERIE_DECISION)
        else:
            msg = (
                "📄 Encontré un artículo similar sobre este tema.\n\n"
                "Podés **Actualizar el existente** para sumar tu aporte, "
                "elegir **Es un tema distinto** o **Volver**."
            )
            return msg, list(OPCIONES_ENRIQUECER_DESCARTAR)

    if est == EstadoFlujo.ESPERANDO_TEXTO:
        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            return (
                "📄 Tenés cargado el artículo base en el editor.\n\n"
                "Hacé los cambios necesarios y tocá **Confirmar texto**, o elegí **Es un tema distinto** para empezar de cero.",
                ["confirmar_texto", "descartar", "volver"],
            )
        return (
            "✍️ Escribí o pegá el contenido de tu artículo acá abajo y tocá **Confirmar texto** cuando esté listo.",
            ["confirmar_texto", "volver"],
        )

    if est == EstadoFlujo.DECISION_TEXTO:
        return (
            "🔍 Encontré un articulo con contenido muy similar.\n\n"
            "Podés **Enriquecer el existente** para sumar tu aporte, o **Continuar con mi texto** si tu caso es diferente.",
            list(OPCIONES_ENRIQUECER_CONTINUAR),
        )

    if est == EstadoFlujo.ESPERANDO_PLANTILLA:
        return (
            "📋 Elegí el formato de tu artículo abajo: **Instructivo** (paso a paso) o **Soluciones** (resolución de un error).",
            list(OPCIONES_PLANTILLAS),
        )

    if est == EstadoFlujo.ESPERANDO_METADATOS:
        plantilla = (sesion.borrador.tipo_plantilla if sesion.borrador else "") or "artículo"
        return (
            f"🏷️ Seleccioná la categoría y agregá al menos otra etiqueta para clasificar este {plantilla}.",
            ["volver"],
        )

    if est in (EstadoFlujo.REVISION_BORRADOR, EstadoFlujo.SUBSANANDO_BORRADOR):
        if getattr(sesion, "confirmando_rechazo", False):
            return (
                "⚠️ ¿Seguro que querés descartar el borrador? Tocá **Sí, descartar** para cancelarlo definitivamente o **Volver** para conservarlo.",
                ["confirmar_rechazo", "volver"],
            )
        if sesion.validacion and not sesion.validacion.valido:
            return (
                "⚠️ El borrador tiene observaciones bloqueantes. Corregilas en el panel izquierdo y guardá los cambios para continuar.",
                list(OPCIONES_REVISION_BLOQUEANTE),
            )
        return (
            "✅ El borrador superó las validaciones mínimas. Si estás conforme con el contenido, tocá **Estoy conforme**.",
            list(OPCIONES_REVISION_VALIDO),
        )


    if est in (EstadoFlujo.CONFORMIDAD_USUARIO, EstadoFlujo.RECHAZADO):
        return (
            msg_sesion_finalizada(est.value),
            OPCIONES_REINICIAR,
        )

    return (
        "💡 Podés continuar escribiendo o tocar **Empezar de nuevo** para reiniciar.",
        OPCIONES_REINICIAR,
    )