# IncidentIQ

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # INCIDENTIQ_DATABASE_URL is required
```

Run the API:

```bash
uvicorn app.main:app_factory --factory --reload
```

Run tests:

```bash
pytest
```

## Configuration

Settings live in `app/config.py` (`Settings`) and are read from `INCIDENTIQ_*`
environment variables or `.env`. `INCIDENTIQ_DATABASE_URL` is required; startup
fails with a validation error if it is missing or any value is invalid.
In tests, pass explicit settings: `create_app(Settings(database_url=..., environment="test"))`.
