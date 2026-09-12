from fastapi import APIRouter
from backend.app.services.state_service import get_state

router = APIRouter()


@router.get("/state")
def state():
    return get_state()