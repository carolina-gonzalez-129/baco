from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# defining api endpoint
@app.get("/")
async def first_example():
    return {"message": "Es reactiva? Si xd"}

## para correr el server : uvicorn my_agent.api.main:app --reload --host 127.0.0.1 --port 8080
#Todas las routes tienen q tener @app.laruta(parametros opcionales)

 ##Si el parametro es una ruta usar {} en la url del decorator ej
 #@app.get("/items/{item_id}")
 #y si es query no va en la url, solo va como argumento ej
 #@app.get("/items/")
#


