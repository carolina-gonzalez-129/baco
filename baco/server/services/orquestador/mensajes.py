from typing import Any, Dict, List, Optional, Tuple

from baco.server.schemas.chat_orquestado import EstadoFlujo


MENSAJE_BIENVENIDA = (
    "🤖 ¡Hola! Soy BACO, tu asistente en la Base de Conocimiento de Finnegans.\n\n"
    "Para comenzar, **escribí el título** de lo que te gustaría publicar. "
    "Una buena fórmula es incluir la acción y el módulo (por ejemplo: *Configurar punto de venta en Ventas*).\n\n"
)

def msg_cambios_guardados(cambios, descartes) -> str:
    """Detalla qué se guardó y qué no (con motivo) al guardar desde el panel."""
    cambios = list(cambios or [])
    descartes = list(descartes or [])
    partes = []
    if cambios:
        partes.append("Guardé tus cambios:\n" + "\n".join(f"- **{c}**: {d}" for c, d in cambios))
    if descartes:
        partes.append("No apliqué:\n" + "\n".join(f"- **{c}**: {d}" for c, d in descartes))
    if not partes:
        return "No había cambios para guardar."
    return "\n\n".join(partes)
OPCIONES_ENRIQUECER_DESCARTAR = ["enriquecer", "descartar"]
OPCIONES_SERIE_DECISION = ["actualizar", "descartar"]
OPCIONES_ENRIQUECER_CONTINUAR = ["enriquecer", "continuar"]
OPCIONES_PLANTILLAS = ["instructivo", "soluciones"]
OPCIONES_REVISION_VALIDO = ["auditar", "continuar"]
OPCIONES_REVISION_BLOQUEANTE = ["editar", "rechazar"]

OPCIONES_REVISION_INTERMEDIA_VALIDO = ["aplicar_plantilla", "continuar"]
OPCIONES_CONFIRMAR_RECHAZO = ["confirmar_rechazo", "cancelar_rechazo"]
OPCIONES_REINICIAR = ["reiniciar"]
OPCIONES_FINALIZADO = ["ver_articulo_final"]
OPCIONES_EDICION_FINAL = ["finalizar"]
OPCIONES_CONFIRMAR_PLANTILLA = ["confirmar_plantilla", "cancelar_plantilla"]

DESCRIPTORES_BOTONES: Dict[str, Dict[str, str]] = {
    "volver": {"accion": "volver", "label": "Volver", "estilo": "btn-ghost"},
    "confirmar_texto": {"accion": "confirmar_texto", "label": "Confirmar texto", "estilo": "btn-primary"},
    "enriquecer": {"accion": "enriquecer", "label": "Enriquecer el existente", "estilo": "btn-dark"},
    "actualizar": {"accion": "actualizar", "label": "Actualizar el existente", "estilo": "btn-dark"},
    "descartar": {"accion": "descartar", "label": "Es un tema distinto", "estilo": "btn-ghost"},
    "continuar": {"accion": "continuar", "label": "Continuar", "estilo": "btn-primary"},
    "instructivo": {"accion": "instructivo", "label": "Instructivo", "estilo": "btn-dark"},
    "soluciones": {"accion": "soluciones", "label": "Soluciones", "estilo": "btn-dark"},
    "aplicar_plantilla": {"accion": "aplicar_plantilla", "label": "Aplicar plantilla", "estilo": "btn-dark"},
    "auditar": {"accion": "auditar", "label": "Auditar", "estilo": "btn-dark"},
    "editar": {"accion": "editar", "label": "Seguir editando", "estilo": "btn-ghost"},
    "seguir_editando": {"accion": "seguir_editando", "label": "Seguir editando", "estilo": "btn-ghost"},
    "rechazar": {"accion": "rechazar", "label": "Descartar borrador", "estilo": "btn-ghost"},
    "confirmar_rechazo": {"accion": "confirmar_rechazo", "label": "Sí, descartar", "estilo": "btn-peligro"},
    "cancelar_rechazo": {"accion": "cancelar_rechazo", "label": "No, conservarlo", "estilo": "btn-ghost"},
    "aceptar_metadatos": {"accion": "aceptar_metadatos", "label": "Mantener categoría y tags", "estilo": "btn-primary"},
    "rechazar_metadatos": {"accion": "rechazar_metadatos", "label": "Elegir otros", "estilo": "btn-secondary"},
    "enviar_datos": {"accion": "enviar_datos", "label": "Enviar datos", "estilo": "btn-primary"},
    "ayuda": {"accion": "ayuda", "label": "¿Qué hago acá?", "estilo": "btn-ghost"},
    "reiniciar": {"accion": "reiniciar", "label": "Empezar de nuevo", "estilo": "btn-ghost"},
    "ver_articulo_final": {"accion": "ver_articulo_final", "label": "Ver artículo", "estilo": "btn-primary"},
    "finalizar": {"accion": "finalizar", "label": "Finalizar", "estilo": "btn-primary"},
    "confirmar_plantilla": {"accion": "confirmar_plantilla", "label": "Sí, cambiar plantilla", "estilo": "btn-peligro"},
    "cancelar_plantilla": {"accion": "cancelar_plantilla", "label": "Cancelar", "estilo": "btn-ghost"},
}

MSG_VOLVER_TITULO = (
    "Volvemos al paso anterior. Ingresá un nuevo **título** para tu artículo:"
)
MSG_VOLVER_TEXTO = (
    "Volvemos al paso anterior. Ingresá el **texto** corregido para tu artículo:"
)
MSG_VOLVER_TEXTO_ACTUALIZADO = (
    "Volvemos al paso anterior. Ingresá el **texto actualizado** para tu artículo:"
)
MSG_VOLVER_PLANTILLA = (
    "Volvemos a la selección de formato. ¿Qué **tipo** de plantilla preferís para este artículo?"
)
MSG_VOLVER_METADATOS = (
    "Volvemos al paso anterior. Podes corregir **la categoría y los tags tematicos** para clasificar tu artículo:"
)
MSG_VOLVER_ENRIQUECER_O_DESCARTAR = (
    "Volvemos al paso anterior. ¿Deseás **enriquecer** el artículo encontrado o **descartarlo**?"
)
MSG_OPERACION_CANCELADA = (
    "Operación cancelada. Mantenemos tu borrador intacto:\n\n"
)


MSG_SIN_COINCIDENCIAS_TITULO = (
    "No encontré nada parecido. Por favor, enviame el texto o desarrollo del artículo."
)
MSG_DESCARTAR_COINCIDENCIA_TITULO = (
    "✨ Seguimos con tu propuesta de artículo.\n\n"
    "Escribí o pegá el contenido acá abajo y tocá **Confirmar texto** cuando esté listo."
)
MSG_TEXTO_EN_EDICION = (
    "📝 Guardé tu texto en el editor.\n\n"
    "Podés seguir escribiendo o pegando más contenido, y cuando esté listo tocá **Confirmar texto**."
)
MSG_ELEGIR_PLANTILLA = (
    "📋 Elegí el formato para tu artículo:\n\n"
    "Tocá **Instructivo** si es un paso a paso, o **Soluciones** si resuelve un error o consulta.\n\n"
    "Vas a poder editar el título y el texto en el paso siguiente."
)
MSG_PEDIR_EDICION = "Hacé los cambios que necesites en el **Editor**."
MSG_RECHAZADO = (
    "Cancelamos el borrador y no se guardó ningún cambio. "
    "Si querés comenzar otra redacción desde el principio, tocá **Empezar de nuevo**."
)
MSG_SESION_EXPIRADA = (
    "Tu sesión se cerró por inactividad. Para retomar, escribí el título del artículo o tocá **Empezar de nuevo**."
)

PREFIJO_SIN_DUPLICADOS = ""
PREFIJO_CONTINUAR_PROPIO = ""
PREFIJO_METADATOS_REGISTRADOS = ""
PREFIJO_BORRADOR_ACTUALIZADO = " "
PREFIJO_ERROR_CONFORMIDAD = "Tuvimos problemas al registrar tu conformidad"

MSG_CATEGORIA_TAGS_COMPLETOS = (
    "¡Listo! Antes de seguir, ¿querés que revise tu artículo según las pautas editoriales? "
    "Tocá **Auditar**.\n"
    "Si preferís avanzar así, tocá **Continuar**.\n\n"
    "Si querés hacer cambios antes, editá lo que necesites en el panel y tocá **Guardar cambios**."
)

MSG_PLANTILLA_VALIDADA = (
    "¡Perfecto! ¿Querés que le dé a tu artículo el formato estándar de su tipo? "
    "Tocá **Aplicar Plantilla**.\n"
    "Si ya tiene ese formato, tocá **Continuar**.\n\n"
)
MSG_ANTES_DE_FINALIZAR = MSG_CATEGORIA_TAGS_COMPLETOS
MSG_ANTES_DE_CONTINUAR = MSG_PLANTILLA_VALIDADA
MSG_OPCION_NO_DISPONIBLE = "Esa opción no está disponible en este paso. Elegí una de las opciones de abajo."
MSG_CONFIRMAR_RECHAZO = (
    "¿Estás seguro de que querés descartar todo el artículo? Se perderán los cambios realizados en esta sesión."
)


def msg_plantilla_a_aplicar(tipo_plantilla) -> str:
    """Antes de ejecutar la skill: qué tipo de plantilla se va a usar."""
    tipo = (tipo_plantilla or "").strip().capitalize()
    if not tipo:
        return ""
    return f"Se va a aplicar la plantilla **{tipo}**. Si no es el tipo correcto, cambialo en el panel antes de aplicarla."
MSG_BORRADOR_FINALIZADO = (
    "✅ Registramos tu borrador.\n\n"
    "Todavía no está publicado: la aprobación y publicación final las hace un moderador."
)


MSG_EDICION_FINAL = (
    "¡Último paso! Revisá tu artículo: podés editar el título, el texto, la categoría, el tipo de plantilla y los tags tematicos.\n\n"
    "Cuando esté todo bien, tocá **Finalizar**: registramos el borrador y ya no vas a poder editarlo; "
    "después lo revisa y publica un moderador."
)


def prefijo_borrador_creado(articulo_id: int) -> str:
    return ""


def msg_coincidencia(res_msg: str, titulo: str, url: str) -> str:
    return f"{res_msg} ({titulo} - {url})"


VARIANTES_TEXTO_VACIO = [
    "Necesito que me pases el texto o los pasos del artículo para que podamos armarlo juntos. Pegalo o redactalo acá abajo cuando gustes.",
    "El mensaje me llegó en blanco, probá pegando de nuevo el contenido acá.",
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
        "Este artículo es demasiado largo para editarlo desde el chat (más de 15.000 caracteres). "
        "Tocá **Es un tema distinto** para escribir uno nuevo, o **Empezar de nuevo**."
    )


def msg_enriquecer_cargado(articulo_id: int, titulo: str) -> str:
    return (
        f"📄 Cargué el artículo ('{titulo}') en la **Vista previa** .\n\n"
        "Hacé los cambios que necesites y toca **Confirmar texto**."
    )


def msg_actualizar_serie_cargado(articulo_id: int, titulo: str) -> str:
    return (
        f'📄 Cargué la ultima publicación de la serie ("{titulo}") en la **Vista previa** .\n\n'
        "Hace los cambios que necesites y toca **Confirmar texto**."
    )


VARIANTES_OPCION_INVALIDA = [
    "Disculpá, no llegué a interpretar bien lo que me enviaste. Para que no tengas que escribirlo a mano, podés tocar directamente uno de los botones que te aparecen en pantalla.",
    "No te preocupes, a veces me confundo si no usamos la palabra exacta. Para que avancemos sobre seguro, elegí **Enriquecer el existente** (o **Actualizar el existente**) si querés aprovechar lo que ya existe en la base, o **Es un tema distinto** si preferís ingresar tu contenido aparte.",
]


def msg_opcion_invalida(intento: int = 0) -> str:
    return VARIANTES_OPCION_INVALIDA[intento % len(VARIANTES_OPCION_INVALIDA)]


VARIANTES_TAGS_FALTANTES = [
    "¡Ya casi lo tenemos listo! Sumale al menos una etiqueta temática",
]


VARIANTES_CATEGORIA_FALTANTE = [
    "Sólo falta la **categoría**: elegila en el menu y tocá **Enviar datos**.",
]


OPCIONES_CONFIRMAR_METADATOS = ["enviar_datos", "volver"]


def msg_confirmar_metadatos(categoria: str, tags: List[str]) -> str:
    """Carga por chat completa: se confirma con Enviar datos, igual que desde el panel."""
    tags_txt = ", ".join(tags) if tags else "sin etiquetas"
    txt_etiqueta = "las etiquetas temáticas" if len(tags) > 1 else "la etiqueta temática"
    return (
        f"Listo, cargué la categoría **{categoria}** y {txt_etiqueta} **{tags_txt}**. "
        "Editalas si lo precisas y tocá **Enviar datos** para seguir."
    )


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
    return f"Para clasificar {art}, elegí una categoría y sumá al menos una etiqueta además del tipo de plantilla."


def msg_pedir_tag_adicional(plantilla: str = "", intento: int = 0) -> str:
    return VARIANTES_TAGS_FALTANTES[intento % len(VARIANTES_TAGS_FALTANTES)]


def msg_pedir_plantilla(prefijo: str = "") -> str:
    return f"{prefijo}{MSG_ELEGIR_PLANTILLA}"


def msg_pedir_metadatos(plantilla: str, prefijo: str = "") -> str:
    return (
        f"{prefijo}🏷️ Tipo de plantilla **{plantilla.capitalize()}**.\n\n"
        "Para seguir, sumá al menos una etiqueta más y elegí la categoría. "
    )


def msg_sesion_finalizada(estado_valor: str) -> str:
    accion = "descartado" if estado_valor in (EstadoFlujo.RECHAZADO.value, "rechazado") else "enviado a revisión"
    return f"Este artículo ya fue {accion}. Para escribir uno nuevo, tocá **Empezar de nuevo**."


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
                "o elegir **Es un tema distinto**."
            )
            return msg, list(OPCIONES_SERIE_DECISION)
        else:
            msg = (
                "📄 Encontré un artículo similar sobre este tema.\n\n"
                "Podés **Actualizar el existente** para sumar tu aporte, "
                "o elegir **Es un tema distinto**."
            )
            return msg, list(OPCIONES_ENRIQUECER_DESCARTAR)

    if est == EstadoFlujo.ESPERANDO_TEXTO:
        if sesion.borrador is not None and sesion.borrador.modo == "enriquecimiento":
            return (
                "📄 Tenés cargado el artículo base en el editor.\n\n"
                "Hacé los cambios necesarios y tocá **Confirmar texto**, o elegí **Es un tema distinto** para empezar de cero.",
                ["confirmar_texto", "descartar"],
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

    if est in (EstadoFlujo.REVISION_TIPO, EstadoFlujo.REVISION_METADATOS):
        if getattr(sesion, "confirmando_rechazo", False):
            return (
                "⚠️ ¿Seguro que querés descartar el borrador? Tocá **Sí, descartar** para cancelarlo definitivamente o **No, conservarlo** para seguir.",
                list(OPCIONES_CONFIRMAR_RECHAZO),
            )
        if sesion.validacion and not sesion.validacion.valido:
            return (
                "⚠️ El borrador tiene observaciones **bloqueantes**. Corregilas en el panel izquierdo y guardá los cambios para continuar.",
                list(OPCIONES_REVISION_BLOQUEANTE),
            )
        from baco.server.services.orquestador.contrato import auditado, plantilla_aplicada

        if (est == EstadoFlujo.REVISION_TIPO and plantilla_aplicada(sesion)) or (
            est == EstadoFlujo.REVISION_METADATOS and auditado(sesion)
        ):
            return ("Revisá el resultado en la **Vista previa** y tocá **Continuar** cuando esté listo.", ["continuar"])
        if est == EstadoFlujo.REVISION_TIPO:
            return (
                "¿Querés darle formato estándar a tu texto? Usá **Aplicar plantilla** en el panel, o seguí editando.",
                list(OPCIONES_REVISION_INTERMEDIA_VALIDO),
            )
        return (
            "Tu borrador está listo para revisar.",
            list(OPCIONES_REVISION_VALIDO),
        )


    if est == EstadoFlujo.EDICION_FINAL:
        return (
            MSG_EDICION_FINAL,
            list(OPCIONES_EDICION_FINAL),
        )

    if est in (EstadoFlujo.FINALIZADO, EstadoFlujo.RECHAZADO):
        return (
            msg_sesion_finalizada(est.value),
            OPCIONES_REINICIAR,
        )

    return (
        "💡 Podés continuar escribiendo o tocar **Empezar de nuevo** para reiniciar.",
        OPCIONES_REINICIAR,
    )

MSG_CAMBIO_PLANTILLA_DESCARTADO = (
    "ℹ️ Descarté el cambio de tipo de plantilla que estaba pendiente de confirmar: "
    "el tipo quedó como estaba."
)

MSG_CAMBIO_PLANTILLA_CANCELADO = (
    "Listo, **no cambié** el tipo de plantilla. Todo quedó como estaba.\n\n"
    "Cuando esté todo listo, tocá **Finalizar**."
)


def msg_confirmar_cambio_plantilla(actual: str, nueva: str) -> str:
    return (
        f"⚠️ **CUIDADO:** estas por modificar el tipo de plantilla de **{actual or 'sin plantilla'}** "
        f"a **{nueva}**. El **texto se va a actualizar** según la nueva plantilla "
        "(se reaplica la skill de plantillas).\n\n"
        "Partimos de tu texto actual, con tus ediciones "
        "El resultado del **auditor** no se vuelve a correr. Mantenemos tus cambios en todo lo demas\n\n"
        "¿Estás seguro? Si rechazás, el artículo se queda con el tipo que tiene."
    )


MSG_ELEGIR_UNA_PLANTILLA = (
    "Elegí **uno solo** tipo de plantilla: **instructivo** o **soluciones**. "
    "No cambié el tipo de plantilla; el resto de los cambios quedó guardado."
)


def msg_plantilla_obligatoria(actual: str) -> str:
    return (
        "El **tipo de plantilla** es obligatorio, así que no lo quité"
        + (f": sigue siendo **{actual}**" if actual else "")
        + ". El resto de los cambios quedó guardado.\n\n"
        "Si querés cambiarlo, elegí **instructivo** o **soluciones** desde el panel o escribiéndolo acá.\n\n"
        "Al tocar **Finalizar** registramos el borrador y ya no vas a poder editarlo; después lo revisa y publica un moderador."
    )


def msg_plantilla_sin_cambio(actual: str) -> str:
    return (
        f"El tipo de plantilla ya es **{actual}**, no hay nada que cambiar.\n\n"
        "Al tocar **Finalizar** registramos el borrador y ya no vas a poder editarlo; después lo revisa y publica un moderador."
    )
