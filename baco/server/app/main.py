from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Precalentar ambos modelos de embeddings en el arranque del servidor, no al importar
    from baco.server.services.embeddings import get_model_titulo, get_model_texto
    get_model_titulo()
    get_model_texto()
    yield


app = FastAPI(lifespan=lifespan)

#Esto es para que despues conectemos el front con el back
#y quizas porque se pueden añadir varias validaciones deterministas aca.
#Es rest y mas orientada a async/await,  mas rapida
#supuestamente q flask y django
#IMPORTANTE : Emiliano habia dicho que era bueno que respecto al titulo
#la comprobacion sea asincrona
#Deberia quizas ver si necesito un manejador de estados
#Lo de persistencia de sesion quizas se maneje desde aca para lo de borradores
#pydantic es una herramienta para validar data
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
#ASEGURARSE DESPS DE Q EL CORS ESTE PARA Q PUEDAN USARLO DESDE CUALQUIER WEB NO SO

# defining api endpoint
@app.get("/")
async def first_example():
    return {"message": "Es reactiva? Si xd"}

## para correr el server : uvicorn main:app --reload --host localhost --port 8080  (mejor usar loclahost q el 127.0.0 para q
#cuando hagan el front tmb corran en localhost y no haya problemas
#Todas las routes tienen q tener @app.laruta(parametros opcionales)

 ##Si el parametro es una ruta usar {} en la url del decorator ej
 #@app.get("/items/{item_id}")
 #y si es query no va en la url, solo va como argumento ej
 #@app.get("/items/")
#
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("baco.server.app.main:app", host="localhost", port=8080, reload=True)

##IMPORTANTE : Como el servidor va a ser usado por agentes quizas estaria bueno configurar q
#sea un mcp server si eso compatibiliza con q pueda usarse tmb por usuairos (tiene sentido si vemos lo q nos pasaron ellos
#osea solo difiere en como se autentica pero

#IMPORTANTE 2 : hay que agotar la capa determinista antes de pedirle cosas al agente en si
#aunque desde la interfaz de usuario todo parezca como del agente!

#session_backend = RedisBackend(url="redis://localhost:6379/0")



#
# @app.get("/profile")
# async def profile(request: Request):
#     # Retrieve data on subsequent requests
#     user_id = request.session.get("user_id")
#     if not user_id:
#         return {"error": "Not authenticated"}
#     return {"user_id": user_id}
#
# @app.post("/logout")
# async def logout(request: Request):
#     # Clear the session data from Redis and the cookie
#     request.session.clear()
#     return {"message": "Logged out successfully"}

