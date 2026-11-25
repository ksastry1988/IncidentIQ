# IncidentIQ

IncidentIQ is an incident investigation service. It accepts operational alerts,
persists incident metadata, and is designed to support evidence gathering and
root-cause analysis. The current application provides configuration, health
checks, PostgreSQL incident persistence, and simulated log, metrics,
deployment, and dependency sources. MCP integration for these sources is in
progress (see below).

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

## Query simulated deployment history

The independent deployment-history source returns deployments for a service
within a lookback window ending at `as_of`:

```bash
curl -G http://localhost:8000/api/v1/simulated/deployments \
  --data-urlencode 'service=payments' \
  --data-urlencode 'as_of=2026-11-17T12:00:00Z' \
  --data-urlencode 'lookback_minutes=60'
```

`lookback_minutes` defaults to 1440 and may be 1–10080. The window is
inclusive and `as_of` must be timezone-aware. Each deployment has
`deployment_id`, `service`, `version`, `timestamp`, `status` (`succeeded`,
`failed`, or `rolled_back`), and `change_summary`, ordered oldest first. No
matches return `deployment_count: 0` and an empty `deployments` list. The
fixtures include a payments regression deployment (`dep-1002`, 11:55 UTC on
2026-11-17) shortly before the incident. Source failure returns `503` with
`detail.code` set to `simulated_deployment_source_unavailable`.

## Query simulated service dependencies

The independent dependency source returns the services related to a service:

```bash
curl -G http://localhost:8000/api/v1/simulated/dependencies \
  --data-urlencode 'service=checkout'
```

Each relationship has `service`, `direction` (`depends_on` when the requested
service relies on it, `depended_on_by` when it relies on the requested
service), `depth` (1 is direct, higher is transitive), and `path` (the call
path from caller to callee). Results are ordered by direction, depth, then
service and cover only the requested service's graph. A service with no known
dependencies returns `relationship_count: 0` and an empty `relationships`
list. The fixtures include the checkout → inventory → inventory-db
downstream-degradation path, plus unrelated services such as search. Source
failure returns `503` with `detail.code` set to
`simulated_dependency_source_unavailable`.

To look up the dependencies of an incident's affected service, call
`GET /api/v1/incidents/{incident_id}/dependencies`. It returns the same fields
plus `incident_id`; an unknown incident returns `404`.

## Roadmap: MCP integration for investigation tools

Issue #5 (Task 3/9) is split into independently testable subtasks, each with
its own acceptance criteria. Update this table as subtasks land.

| Subtask | Issue | Status |
| --- | --- | --- |
| MCP adapter interface, tool schemas, result envelope | #31 | Done |
| Simulated-source adapters exposed via MCP server | #32 | Done |
| Service/environment authorization and read-only enforcement | #33 | Done |
| Configurable timeouts and distinct source-error handling | #34 | Planned |
| Sensitive-data redaction and credential isolation | #35 | Planned |
| Worker MCP client integration and end-to-end tests | #36 | Planned |

### Adapter interface and result envelope

`app/investigation_tools` defines the read-only tool layer, independent of any
MCP server or worker. `ToolAdapter` (`adapters.py`) has one implementation per
tool: `LogsAdapter`, `MetricsAdapter`, `DeploymentsAdapter`, and
`DependenciesAdapter`. Each exposes `input_schema()` (JSON Schema) and
`execute(arguments)`, which validates the arguments, calls `fetch(params)` on its
source (the simulated sources by default; inject fakes for tests), and returns a
`ResultEnvelope`. Subclasses only implement `fetch`.

Parameters (`schemas.py`): every tool requires `service` and `environment`;
logs, metrics, and deployments also require timezone-aware `start` and `end`.
Logs additionally accept `severity`, `error_pattern`, and `correlation_id`.
Metrics compare the window with the equal-length window before `start`.
Invalid input raises `pydantic.ValidationError`: missing fields, naive
datetimes, `end` before `start`, a range longer than
`ToolLimits.max_time_range` (default 24h), or a `limit` above
`ToolLimits.max_limit` (default 200). `limit` defaults to
`ToolLimits.default_limit` (50); results never exceed it.

Every result uses one envelope:

| Field | Meaning |
| --- | --- |
| `source` | Name of the backing source |
| `tool` | `logs`, `metrics`, `deployments`, or `dependencies` |
| `service`, `environment` | Echo of the request |
| `query` | Validated parameters, including the resolved `limit` |
| `items` | Result records, at most `limit` |
| `truncated` | `true` when more matching records existed than `limit` |
| `retrieved_at` | UTC timestamp of retrieval |

`ToolRegistry` (`mcp.py`) is the MCP-facing layer, without depending on an MCP
SDK. `list_tools()` returns `tools/list`-shaped descriptors (`name`,
`description`, `inputSchema`, `readOnlyHint`). `call_tool(name, arguments)`
returns a `tools/call`-shaped result: `structuredContent` holds the envelope on
success; unknown tools and validation failures return `isError: true` with
per-field `validation_errors`.

### MCP server

`app/investigation_tools/server.py` serves the registry over MCP (stdio). Start
it locally with:

```bash
python -m app.investigation_tools.server
```

It registers exactly four read-only tools; no mutating tool exists. All take
`service` and `environment` (required); the time-ranged tools also take
`start` and `end` (ISO 8601 with timezone) and optional `limit`.

| Tool | Parameters | `source` |
| --- | --- | --- |
| `logs` | `service`, `environment`, `start`, `end`, `severity`, `error_pattern`, `correlation_id`, `limit` | `simulated-logs` |
| `metrics` | `service`, `environment`, `start`, `end`, `limit` | `simulated-metrics` |
| `deployments` | `service`, `environment`, `start`, `end`, `limit` | `simulated-deployments` |
| `dependencies` | `service`, `environment`, `limit` | `simulated-dependencies` |

A valid query with no matches returns a successful result with `items: []`.
Tests use an in-process client: `async with Client(create_server()) as c`.

### Access policy

Every `call_tool` is authorized before any source is queried, using allow-lists
from settings (comma-separated, case- and whitespace-insensitive):

| Variable | Default |
| --- | --- |
| `INCIDENTIQ_TOOL_ALLOWED_SERVICES` | `checkout,fraud-check,inventory,inventory-db,payments,search,search-index` |
| `INCIDENTIQ_TOOL_ALLOWED_ENVIRONMENTS` | `production,staging` |

An empty list allows nothing. A `service` or `environment` that is not allowed
(or not a string) returns `isError: true` with
`structuredContent: {"error": "access_denied", "field": "service"}`. Variants
such as `" PAYMENTS "` are normalized (NFKC, trim, casefold) and replaced with the
configured spelling before the adapter runs. Denials are logged with the tool and
field only, never the submitted values. Adapters expose only `execute`,
`fetch`, and `input_schema`; a test asserts no mutating method or tool exists.

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
