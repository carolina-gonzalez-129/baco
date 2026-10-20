from baco.server.services.orquestador.coordinador import manejar_turno
from baco.server.services.orquestador.sesion import (
    actualizar_borrador_texto,
    obtener_borrador_aprobado,
    obtener_borrador_sesion_validado,
)

# PAQUETE PARA DESACOPLAR EL ARCHIVO DE ORQUESTADOR.PY EN 6 SUBSISTEMAS
# 1) COORDINADOR, SE ENCARGA DE SER EL PUNTO UNIFICADO DESDE API.PY PARA LO DE SIMULAR EL CHAT
# 2) HANDLERS, SE ENCARGAN DE LA TRANSICIÓN DE ESTADOS
# 3) MENSAJES , SE ENCARGAN DE GUARDAR LOS TEXTOS Q VA A USAR EL ORQUESTADOR
# 4) SESION , SE ENCARGA DE MANEJAR EL CICLO DE VIDA Y ALMACENAMIENTO DE SESIONES
# VALIDACIONES, SE ENCARGA DE PEDIR VALIDACIONES VALIDAR_ARTICULO Y DE APLICAR OTRAS ESPECIFICAS DE LO Q SE RECIBE AL RECIBIR LA PETICION HTTP


__all__ = [
    "manejar_turno",
    "obtener_borrador_sesion_validado",
    "obtener_borrador_aprobado",
    "actualizar_borrador_texto",
]
