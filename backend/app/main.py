from fastapi import FastAPI
from backend.app.routes.analyze import router as analyze_router
from backend.app.routes.emergency import router as emergency_router
from backend.app.routes.state import router as state_router

app = FastAPI()

app.include_router(emergency_router)
app.include_router(state_router)
app.include_router(analyze_router)


@app.get("/")
def home():
    return {
        "message": "Emergency Green Corridor Backend Running"
    }