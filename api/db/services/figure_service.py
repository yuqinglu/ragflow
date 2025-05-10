from api.db.db_models import Figure
from api.db.services.common_service import CommonService

class FigureService(CommonService):
    model = Figure
