from ninja import Router, Schema

from .models import Lot

router = Router(tags=["Référentiel"])


class LotOut(Schema):
    id: int
    code: str
    intitule: str


@router.get("/lots", response=list[LotOut])
def lister_lots(request):
    return Lot.objects.filter(actif=True)
