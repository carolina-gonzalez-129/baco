"""Helpers de flujo para los tests del orquestador.

Todos los flujos (nuevo, enriquecer, actualizar) convergen después de duplicados:
ESPERANDO_PLANTILLA -> REVISION_TIPO -> ESPERANDO_METADATOS -> REVISION_METADATOS
-> EDICION_FINAL -> FINALIZADO.

`avanzar_hasta` recorre ese tramo con las acciones por defecto de cada paso, para que
un test que solo necesita llegar a un estado no repita los pasos intermedios.
"""
from baco.server.schemas.chat_orquestado import EstadoFlujo

ORDEN = [
    EstadoFlujo.ESPERANDO_PLANTILLA,
    EstadoFlujo.REVISION_TIPO,
    EstadoFlujo.ESPERANDO_METADATOS,
    EstadoFlujo.REVISION_METADATOS,
    EstadoFlujo.EDICION_FINAL,
    EstadoFlujo.FINALIZADO,
]


def _cuerpo_paso(estado, plantilla, tags, categoria_id):
    if estado == EstadoFlujo.ESPERANDO_PLANTILLA:
        return {"accion": plantilla}
    if estado in (EstadoFlujo.REVISION_TIPO, EstadoFlujo.REVISION_METADATOS):
        return {"accion": "continuar"}
    if estado == EstadoFlujo.ESPERANDO_METADATOS:
        cuerpo = {"accion": "enviar_datos"}
        if tags is not None:
            cuerpo["tags"] = tags
        if categoria_id is not None:
            cuerpo["categoria_id"] = categoria_id
        return cuerpo
    if estado == EstadoFlujo.EDICION_FINAL:
        return {"accion": "finalizar"}
    raise AssertionError(f"avanzar_hasta no sabe avanzar desde {estado}")


def avanzar_hasta(client, sid, resp, destino, plantilla="instructivo", tags=None, categoria_id=None):
    """Avanza por POST /chat desde `resp` (dict de la última respuesta) hasta `destino`.

    En ESPERANDO_METADATOS envía `tags`/`categoria_id` si se pasan; si no, confirma lo
    precargado (heredados al enriquecer). Falla si un paso no avanza, con el mensaje del back.
    """
    destino = EstadoFlujo(destino)
    assert destino in ORDEN, f"destino fuera del tramo convergente: {destino}"
    while EstadoFlujo(resp["estado"]) != destino:
        estado = EstadoFlujo(resp["estado"])
        assert estado in ORDEN and ORDEN.index(estado) < ORDEN.index(destino), (
            f"no se puede llegar a {destino} desde {estado}"
        )
        nuevo = client.post(
            "/chat",
            json={"session_id": sid, **_cuerpo_paso(estado, plantilla, tags, categoria_id)},
        ).json()
        assert nuevo["estado"] != estado, f"no avanzó desde {estado}: {nuevo.get('mensaje')}"
        resp = nuevo
    return resp
