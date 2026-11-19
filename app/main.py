import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import PlantOutput, ProductionPlanRequest
from .optimizer import InfeasiblePlanError, compute_production_plan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Powerplant production plan")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # FastAPI's default handler echoes the input back, which fails if it contains NaN
    errors = [{"loc": err["loc"], "msg": err["msg"]} for err in exc.errors()]
    logger.warning("Invalid payload: %s", errors)
    return JSONResponse(status_code=422, content={"detail": errors})


@app.post("/productionplan")
def production_plan(payload: ProductionPlanRequest) -> list[PlantOutput]:
    try:
        plan = compute_production_plan(payload)
    except InfeasiblePlanError as e:
        logger.warning("No feasible plan: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Failed to compute the production plan")
        raise HTTPException(status_code=500, detail="Internal server error")

    logger.info("Production plan computed for a load of %s MW", payload.load)
    return plan
