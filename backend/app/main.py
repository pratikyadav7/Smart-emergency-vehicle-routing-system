from fastapi import FastAPI
from backend.app.routes.analyze import router as analyze_router
from backend.app.routes.emergency import router as emergency_router
from backend.app.routes.state import router as state_router
from backend.app.routes.history import router as history_router
from backend.app.routes.dispatch import router as dispatch_router
from backend.app.routes.reroute import router as reroute_router
from backend.app.routes.chaos import router as chaos_router

app = FastAPI()

app.include_router(emergency_router)
app.include_router(state_router)
app.include_router(analyze_router)
app.include_router(history_router)
app.include_router(dispatch_router)
app.include_router(reroute_router)
app.include_router(chaos_router)


@app.get("/")
def home():
    return {
        "message": "Emergency Green Corridor Backend Running"
    }