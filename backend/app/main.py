

from fastapi import FastAPI
from backend.app.routes.emergency import router as emergency_router

app = FastAPI()

app.include_router(emergency_router)


@app.get("/")
def home():
    return {
        "message": "Emergency Green Corridor Backend Running"
    }