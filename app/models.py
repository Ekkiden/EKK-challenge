"""Schemas of the /productionplan request and response."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _on_tenth_grid(value: float) -> float:
    if abs(value * 10 - round(value * 10)) > 1e-6:
        raise ValueError("must be a multiple of 0.1 MW")
    return value


# Power in MW. The plan is computed in steps of 0.1 MW, so a value that is not
# on that grid (e.g. a load of 100.05) could never be matched exactly.
Power = Annotated[float, Field(ge=0), AfterValidator(_on_tenth_grid)]


class _Input(BaseModel):
    # Python's json module accepts NaN and Infinity, we don't.
    model_config = ConfigDict(allow_inf_nan=False)


class Fuels(_Input):
    gas: float = Field(alias="gas(euro/MWh)", ge=0)
    kerosine: float = Field(alias="kerosine(euro/MWh)", ge=0)
    co2: float = Field(alias="co2(euro/ton)", default=0, ge=0)
    wind: float = Field(alias="wind(%)", ge=0, le=100)


class PowerPlant(_Input):
    name: str = Field(min_length=1)
    type: Literal["gasfired", "turbojet", "windturbine"]
    efficiency: float = Field(gt=0, le=1)
    pmin: Power = 0
    pmax: Power

    @model_validator(mode="after")
    def check_pmin_not_above_pmax(self) -> "PowerPlant":
        if self.pmin > self.pmax:
            raise ValueError("pmin cannot be greater than pmax")
        return self


class ProductionPlanRequest(_Input):
    load: Power
    fuels: Fuels
    powerplants: list[PowerPlant] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_names(self) -> "ProductionPlanRequest":
        names = [plant.name for plant in self.powerplants]
        if len(names) != len(set(names)):
            raise ValueError("powerplant names must be unique")
        return self


class PlantOutput(BaseModel):
    name: str
    p: float
