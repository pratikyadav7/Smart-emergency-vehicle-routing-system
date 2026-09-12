from fastapi import APIRouter
from backend.app.services.dispatch_service import dispatch_ambulance

router = APIRouter()


@router.get("/dispatch")
def dispatch():
    return dispatch_ambulance()