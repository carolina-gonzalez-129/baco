from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import sys
from pathlib import Path
#IMPORTANTE : quizas deba usar esto para resolver lo del path my_agent en varios archivos

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# Create a FastAPI app instance
app = FastAPI(
    title="My First FastAPI App",
    description="This is a simple FastAPI application for learning purposes.",
)

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
    uvicorn.run("my_agent.server.api.main:app", host="localhost", port=8080, reload=True)

