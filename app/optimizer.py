"""Unit commitment: how much each powerplant should produce to meet the load at
the lowest cost.

Power is handled in whole steps of 0.1 MW, the precision required for the
response. That allows a dynamic programme over the plants: after the first k
plants, best[t] is the cheapest way to produce exactly t steps with them. Each
plant is either off or runs between its minimum and maximum output, and adding
it to the table costs O(load) (see _add_plant). No external solver is involved.
"""

import math
from collections import deque

from .models import Fuels, PlantOutput, PowerPlant, ProductionPlanRequest

CO2_TONS_PER_MWH = 0.3  # emitted by gas-fired plants, per the challenge statement
EPSILON = 1e-9  # tolerance for floating-point noise in costs and forecasts


class InfeasiblePlanError(Exception):
    """The plants cannot deliver exactly the requested load."""


def to_steps(mw: float) -> int:
    return round(mw * 10)


def marginal_cost(plant: PowerPlant, fuels: Fuels) -> float:
    """Euros needed to produce 1 MWh with this plant."""
    if plant.type == "windturbine":
        return 0.0
    if plant.type == "gasfired":
        return fuels.gas / plant.efficiency + CO2_TONS_PER_MWH * fuels.co2
    return fuels.kerosine / plant.efficiency


def output_range(plant: PowerPlant, fuels: Fuels) -> tuple[int, int]:
    """Lowest and highest output of the plant when switched on, in 0.1 MW steps."""
    if plant.type == "windturbine":
        # No modulation: a wind turbine produces its forecast or nothing. The
        # forecast is rounded down to the grid so we never count on extra wind.
        forecast_mw = plant.pmax * fuels.wind / 100
        steps = math.floor(forecast_mw * 10 + EPSILON)
        return steps, steps
    return to_steps(plant.pmin), to_steps(plant.pmax)


def compute_production_plan(request: ProductionPlanRequest) -> list[PlantOutput]:
    plants = request.powerplants
    costs = [marginal_cost(plant, request.fuels) for plant in plants]
    ranges = [output_range(plant, request.fuels) for plant in plants]
    load = to_steps(request.load)

    capacity = sum(high for _, high in ranges)
    if capacity < load:
        raise InfeasiblePlanError(
            f"Load of {request.load} MW exceeds the available capacity of {capacity / 10} MW"
        )

    best = [0.0] + [math.inf] * load
    predecessors = []
    for cost, (low, high) in zip(costs, ranges):
        best, previous = _add_plant(best, cost / 10, low, high)
        predecessors.append(previous)

    if best[load] == math.inf:
        raise InfeasiblePlanError(
            "No combination of powerplants can match the load exactly within their pmin/pmax"
        )

    # Walk back from the full load to find what each plant produces.
    steps = [0] * len(plants)
    total = load
    for i in reversed(range(len(plants))):
        before = predecessors[i][total]
        steps[i] = total - before
        total = before

    # Listed in merit order, like the example response of the challenge.
    order = sorted(range(len(plants)), key=lambda i: costs[i])
    return [PlantOutput(name=plants[i].name, p=steps[i] / 10) for i in order]


def _add_plant(
    best: list[float], step_cost: float, low: int, high: int
) -> tuple[list[float], list[int]]:
    """Return the cost table after adding one plant, plus the predecessors.

    Reaching a total t with the plant producing x steps (low <= x <= high)
    costs best[t - x] + x * step_cost. With s = t - x this is
    t * step_cost + (best[s] - s * step_cost), so for every t we want the s
    in [t - high, t - low] with the smallest best[s] - s * step_cost. That
    window moves by one as t grows, so a monotonic deque keeps its minimum
    in amortised O(1).

    previous[t] is the total produced by the earlier plants (t itself when
    this plant stays off).
    """
    new_best = best.copy()  # the plant stays off
    previous = list(range(len(best)))
    window = deque()  # candidate s values, increasing best[s] - s * step_cost

    def key(s: int) -> float:
        return best[s] - s * step_cost

    for t in range(len(best)):
        entering = t - low
        if entering >= 0 and best[entering] < math.inf:
            value = key(entering)
            # On ties the newer candidate wins, so earlier plants get loaded first.
            while window and key(window[-1]) >= value - EPSILON:
                window.pop()
            window.append(entering)
        while window and window[0] < t - high:
            window.popleft()
        if window:
            s = window[0]
            cost = best[s] + (t - s) * step_cost
            if cost < new_best[t] - EPSILON:
                new_best[t] = cost
                previous[t] = s
    return new_best, previous
