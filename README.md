# Powerplant production plan

REST API for the [powerplant coding challenge](https://github.com/gem-spaas/powerplant-coding-challenge):
given a load, the fuel prices and a list of powerplants, it returns how much
each plant should produce so that the load is met at the lowest cost.

## Running it

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8888
```

Or with Docker:

```bash
docker build -t powerplant .
docker run --rm -p 8888:8888 powerplant
```

Then post one of the example payloads:

```bash
curl -X POST http://localhost:8888/productionplan \
     -H "Content-Type: application/json" \
     -d @example_payloads/payload3.json
```

Interactive docs are available at http://localhost:8888/docs.

## Tests

```bash
pytest
```

Besides the unit tests, the suite posts the three example payloads to the API
(payload3 has to give exactly `response3.json`) and compares the optimizer with
a brute-force search on 100 small random cases.

## How it works

**Cost per MWh.** Gas-fired: `gas / efficiency + 0.3 * co2` (emission
allowances, 0.3 t of CO2 per MWh). Turbojet: `kerosine / efficiency`. Wind is
free.

**Wind.** A wind turbine is either off or produces its forecast,
`pmax * wind% / 100`. The response has to be in steps of 0.1 MW, so the
forecast is rounded down to that grid: we never count on more wind than there
is.

**Unit commitment.** Filling the load greedily in merit order doesn't always
work because of pmin. For example, with 20 MW of wind and a gas plant with a
pmin of 10 MW, a load of 25 MW can only be met by switching the wind off.

So the optimizer works in whole steps of 0.1 MW and runs a dynamic programme
over the plants: `best[t]` is the cheapest way to produce exactly `t` steps
with the plants seen so far. A plant is either off or runs between pmin and
pmax, so adding it means finding, for every `t`, the cheapest valid predecessor
in a sliding window. A monotonic deque does that in amortised O(1), so the
whole thing is O(plants x load / 0.1 MW), about 55,000 iterations for
payload3. No external solver is used.

When several plans cost the same (e.g. two identical gas plants), plants are
loaded in the order they appear in the payload. The response lists the plants
in merit order, like `response3.json`.

**Errors.** Invalid payloads (missing fields, negative prices, pmin > pmax,
duplicate names, values not on the 0.1 MW grid...) and loads that cannot be
met exactly return a 422 with the reason. Unexpected errors are logged with
their traceback and return a 500 without exposing internals.

## Limitations

It plans a single hour with the data in the payload: no start-up costs, ramp
rates, minimum up/down times or reserves. Run time is proportional to
plants x load: around 35 ms for payload3, and about 3 s for 54 plants with a
10,000 MW load.

## Layout

```text
app/
  main.py           endpoint, logging and error handling
  models.py         request/response schemas (pydantic)
  optimizer.py      costs and unit commitment
tests/
example_payloads/   examples from the challenge statement
```
