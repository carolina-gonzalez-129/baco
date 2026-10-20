from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from baco.server.services.orquestador import EstadoInvalidoError, SesionNoEncontradaError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SesionNoEncontradaError)
    async def sesion_no_encontrada_handler(request: Request, exc: SesionNoEncontradaError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(EstadoInvalidoError)
    async def estado_invalido_handler(request: Request, exc: EstadoInvalidoError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})
