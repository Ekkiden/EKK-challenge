import itertools
import random

import pytest

from app.models import ProductionPlanRequest
from app.optimizer import (
    InfeasiblePlanError,
    compute_production_plan,
    marginal_cost,
    output_range,
)


def make_request(load, plants, gas=10, kerosine=20, co2=0, wind=0):
    return ProductionPlanRequest.model_validate(
        {
            "load": load,
            "fuels": {
                "gas(euro/MWh)": gas,
                "kerosine(euro/MWh)": kerosine,
                "co2(euro/ton)": co2,
                "wind(%)": wind,
            },
            "powerplants": plants,
        }
    )


def plant(name, type_, pmin, pmax, efficiency=0.5):
    return {"name": name, "type": type_, "efficiency": efficiency, "pmin": pmin, "pmax": pmax}


def produced(request):
    return {item.name: item.p for item in compute_production_plan(request)}


def test_cheapest_plant_is_used_first():
    request = make_request(
        50, [plant("gas", "gasfired", 10, 50), plant("jet", "turbojet", 0, 50, 0.3)]
    )
    assert produced(request) == {"gas": 50.0, "jet": 0.0}


def test_wind_runs_at_its_forecast():
    request = make_request(
        30, [plant("wind", "windturbine", 0, 40, 1), plant("gas", "gasfired", 10, 40)], wind=50
    )
    assert produced(request) == {"wind": 20.0, "gas": 10.0}


def test_wind_is_switched_off_when_pmin_requires_it():
    # With the wind on (20 MW), the gas plant would have to run below its pmin.
    request = make_request(
        25, [plant("wind", "windturbine", 0, 40, 1), plant("gas", "gasfired", 10, 40)], wind=50
    )
    assert produced(request) == {"wind": 0.0, "gas": 25.0}


def test_wind_forecast_is_rounded_down_to_the_grid():
    request = make_request(0, [plant("wind", "windturbine", 0, 1.5, 1)], wind=50)
    assert output_range(request.powerplants[0], request.fuels) == (7, 7)  # 0.75 -> 0.7 MW


def test_pmin_can_make_the_load_unreachable():
    with pytest.raises(InfeasiblePlanError, match="No combination"):
        compute_production_plan(make_request(5, [plant("gas", "gasfired", 10, 50)]))


def test_load_above_total_capacity():
    with pytest.raises(InfeasiblePlanError, match="capacity"):
        compute_production_plan(make_request(100, [plant("gas", "gasfired", 0, 50)]))


def test_co2_price_can_change_the_merit_order():
    # gas: 5 / 0.5 + 0.3 * 100 = 40 EUR/MWh, turbojet: 10 / 0.3 = 33.3 EUR/MWh
    request = make_request(
        10,
        [plant("gas", "gasfired", 0, 10, 0.5), plant("jet", "turbojet", 0, 10, 0.3)],
        gas=5,
        kerosine=10,
        co2=100,
    )
    assert produced(request) == {"gas": 0.0, "jet": 10.0}


def test_zero_load_switches_everything_off():
    request = make_request(
        0, [plant("gas", "gasfired", 10, 50), plant("wind", "windturbine", 0, 20, 1)], wind=80
    )
    assert produced(request) == {"gas": 0.0, "wind": 0.0}


def test_identical_plants_are_loaded_in_payload_order():
    request = make_request(150, [plant("a", "gasfired", 50, 100), plant("b", "gasfired", 50, 100)])
    assert produced(request) == {"a": 100.0, "b": 50.0}


def cheapest_cost_by_brute_force(request):
    """Try every combination of outputs. Only usable for tiny cases."""
    options = []
    for p in request.powerplants:
        low, high = output_range(p, request.fuels)
        step_cost = marginal_cost(p, request.fuels) / 10
        options.append([(0, 0.0)] + [(x, x * step_cost) for x in range(max(low, 1), high + 1)])

    load = round(request.load * 10)
    costs = [
        sum(cost for _, cost in combination)
        for combination in itertools.product(*options)
        if sum(x for x, _ in combination) == load
    ]
    return min(costs, default=None)


def plan_cost(request, plan):
    output = {item.name: item.p for item in plan}
    return sum(output[p.name] * marginal_cost(p, request.fuels) for p in request.powerplants)


def test_matches_brute_force_on_small_random_cases():
    rng = random.Random(20261118)
    for _ in range(100):
        plants = []
        for i in range(rng.randint(1, 4)):
            type_ = rng.choice(["gasfired", "turbojet", "windturbine"])
            pmax = rng.randint(1, 5)
            pmin = 0 if type_ == "windturbine" else rng.randint(0, pmax)
            plants.append(
                plant(f"unit{i}", type_, pmin, pmax, rng.choice([0.3, 0.4, 0.5, 0.8, 1.0]))
            )
        request = make_request(
            rng.randint(0, sum(p["pmax"] for p in plants) * 10) / 10,
            plants,
            wind=rng.choice([0, 25, 50, 75, 100]),
            gas=rng.randint(1, 20),
            kerosine=rng.randint(1, 30),
            co2=rng.randint(0, 30),
        )

        expected = cheapest_cost_by_brute_force(request)
        if expected is None:
            with pytest.raises(InfeasiblePlanError):
                compute_production_plan(request)
            continue

        plan = compute_production_plan(request)
        assert sum(round(item.p * 10) for item in plan) == round(request.load * 10)
        assert plan_cost(request, plan) == pytest.approx(expected)
