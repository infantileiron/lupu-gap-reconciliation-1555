from fastapi import APIRouter,Depends
from src.controllers import conservation as controller
from src.schemas.entities import ConservationInput
from src.services.auth import current,editor
router=APIRouter(prefix="/conservation",tags=["conservation"])
@router.get("")
def list_items(user=Depends(current)): return controller.list_items()
@router.post("",status_code=201)
def create(data:ConservationInput,user=Depends(editor)): return controller.create(data)
@router.get("/{id}")
def detail(id:str,user=Depends(current)): return controller.detail(id)
