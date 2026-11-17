# IncidentIQ

IncidentIQ is an incident investigation service. It accepts operational alerts,
persists incident metadata, and is designed to support evidence gathering and
root-cause analysis. The current application foundation provides configuration,
health checks, and the PostgreSQL incident persistence layer.

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

## Run with Docker

Build and start the API and PostgreSQL database:

```bash
docker compose up --build
```

The API is available at <http://localhost:8000>. The database schema is applied
automatically before the API starts. Stop the containers with `Ctrl+C`; remove
the containers while retaining database data with `docker compose down`. To
also delete the persisted database data, run `docker compose down --volumes`.

## Configuration

Settings live in `app/config.py` (`Settings`) and are read from `INCIDENTIQ_*`
environment variables or `.env`. `INCIDENTIQ_DATABASE_URL` is required; startup
fails with a validation error if it is missing or any value is invalid.
In tests, pass explicit settings: `create_app(Settings(database_url=..., environment="test"))`.

Incident persistence is exposed by `IncidentRepository` in `app/incidents/repository.py`.
It supports typed creation, lookup by incident UUID, and lookup by idempotency key.
The idempotency key is unique in the database; a duplicate create raises a database
integrity error for the calling service to handle.
