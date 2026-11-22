# IncidentIQ

IncidentIQ is an incident investigation service. It accepts operational alerts,
persists incident metadata, and is designed to support evidence gathering and
root-cause analysis. The current application provides configuration, health
checks, PostgreSQL incident persistence, and a simulated log source.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # configure INCIDENTIQ_DATABASE_URL for PostgreSQL
```

Create a PostgreSQL database named `incidentiq`, then apply the schema:

```bash
alembic upgrade head
```

To roll back the incident schema:

```bash
alembic downgrade base
```

Run the API:

```bash
uvicorn app.main:app_factory --factory --reload
```

Run tests:

```bash
pytest
```

## Create an incident

Submit an alert with an `Idempotency-Key` header:

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: alert-001' \
  -d '{
    "service": "payments",
    "title": "Elevated error rate",
    "description": "Payment requests are failing.",
    "severity": "severity 1",
    "environment": "production",
    "detected_at": "2026-11-17T12:00:00Z",
    "initial_symptoms": ["HTTP 500 responses", "Elevated latency"]
  }'
```

Successful requests return `201` with the HLD incident shape: `incident_id`,
`title`, `description`, `severity`, `affected_services`, `created_at`, and
`status`. `affected_services` contains the submitted service. Replaying the same
key and request returns the same incident; using that key for different incident
data returns `409 Conflict`. Severity must be one of `severity 1` through
`severity 5`. Invalid requests return `422`.

## Retrieve an incident

```bash
curl http://localhost:8000/api/v1/incidents/00000000-0000-0000-0000-000000000001
```

The `200` response contains `incident_id`, `service`, `title`, `description`,
`severity`, `environment`, `detected_at`, `initial_symptoms`, `status`, and
`created_at` from storage. An unknown UUID returns `404` with
`detail.code` set to `incident_not_found`; a malformed UUID returns `422`.
If incident storage is unavailable, the API returns `503` with
`detail.code` set to `incident_persistence_unavailable`.

## Query simulated logs

The read-only log source is independent of the database and other sources:

```bash
curl -G http://localhost:8000/api/v1/simulated/logs \
  --data-urlencode 'service=payments' \
  --data-urlencode 'start=2026-11-17T11:00:00Z' \
  --data-urlencode 'end=2026-11-17T13:00:00Z' \
  --data-urlencode 'severity=ERROR' \
  --data-urlencode 'error_pattern=invalid configuration' \
  --data-urlencode 'page_size=20'
```

`service`, `start`, and `end` are required. Times must include a timezone;
the range includes both endpoints. Optional filters can be combined:
`severity` (`INFO`, `WARNING`, or `ERROR`), `error_pattern` (case-insensitive
literal substring of the message), and `correlation_id` (exact match). Service
and correlation ID matches are case-sensitive. Results are ordered by timestamp
then ID. `page` is one-based; `page_size` defaults to 20 and is limited to 100.
The response contains `items`, `page`, `page_size`, and `has_more`. No matches
produce an empty `items` list; invalid queries return `422`, and source failure
returns `503` with `detail.code` set to `simulated_log_source_unavailable`.

The fixed fixtures on 2026-11-17 UTC cover a payments deployment regression
(11:55–12:01), a checkout/inventory downstream degradation (13:00–13:01),
and search resource saturation (14:00–14:01). Failure can be simulated by
injecting `SimulatedLogSource(unavailable=True)` via the `get_log_source`
dependency; no public query parameter enables failure.

## Query simulated metrics

The independent metrics source returns incident and baseline snapshots for a
service:

```bash
curl -G http://localhost:8000/api/v1/simulated/metrics \
  --data-urlencode 'service=payments' \
  --data-urlencode 'incident_start=2026-11-17T12:00:00Z' \
  --data-urlencode 'incident_end=2026-11-17T12:05:00Z' \
  --data-urlencode 'baseline_start=2026-11-17T11:45:00Z' \
  --data-urlencode 'baseline_end=2026-11-17T11:50:00Z'
```

The response includes request volume, P50/P95/P99 latency in milliseconds,
error rate, CPU, and memory. Windows are timezone-aware and inclusive; request
volume is summed and the other metrics are averaged across matching samples;
the latency values are averages of per-sample percentiles, not percentiles
calculated over all requests. Error rate, CPU, and memory are percentages.
A window without samples returns `sample_count: 0`, `data_available: false`,
and null metric values. The fixed fixtures include deployment regression,
downstream degradation, and resource saturation scenarios. Simulated source
failure returns `503` with `detail.code` set to
`simulated_metrics_source_unavailable`.

## Run with Docker

Build and start the API and PostgreSQL database:

```bash
docker compose up --build
```

The API is available at <http://localhost:8000>. The database schema is applied
automatically before the API starts. Stop the containers with `Ctrl+C`; remove
the containers while retaining database data with `docker compose down`. To
also delete the persisted database data, run `docker compose down --volumes`.

To run the tests in a container using the application image:

```bash
docker build -t incidentiq-test .
docker run --rm -v "$PWD/tests:/app/tests:ro" incidentiq-test \
  sh -c 'pip install ".[dev]" && pytest'
```

## Configuration

Settings live in `app/config.py` (`Settings`) and are read from `INCIDENTIQ_*`
environment variables or `.env`. `INCIDENTIQ_DATABASE_URL` is required; startup
fails with a validation error if it is missing or any value is invalid.
In tests, pass explicit settings: `create_app(Settings(database_url=..., environment="test"))`.

Incident persistence is exposed by `IncidentRepository` in `app/incidents/repository.py`.
It supports typed creation, lookup by incident UUID, and lookup by idempotency key.
The idempotency key is unique in the database; a duplicate create raises a database
integrity error for the calling service to handle.
