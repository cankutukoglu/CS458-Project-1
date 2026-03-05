# CS458 Project 1 – ARES

## Requirements

### Login App (`login/`)
- Docker Desktop

### Test Framework (`Core/`)
- Python 3.11+
- `pydantic >= 2.7`
- `pytest >= 8.0`
- `selenium >= 4.20`

---

## Running the Login App

```bash
cd login

# Copy env file and fill in values
cp .env.example .env

# Build and start all services
docker compose up --build
```

| Service    | URL                              |
|------------|----------------------------------|
| Frontend   | http://localhost:8080            |
| Backend    | http://localhost:8080/api/health |
| PostgreSQL | localhost:5433                   |

```bash
# Stop
docker compose down

# Logs
docker compose logs -f
```

---

## Running the Tests

```bash
cd Core

# Install dependencies
pip install -r requirements.txt

# Install a browser driver (e.g. chromedriver via Selenium Manager or manually)

# Copy env file and fill in LLM credentials
cp .env.example .env

# Run all tests
pytest

# Run only browser-backed tests
pytest -m integration

# Run only OAuth tests
pytest -m oauth
```

---

## Environment Variables

### Login App — `login/.env`

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | Yes | Database password |
| `SECRET_KEY` | Yes | Flask session secret |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Yes | Google OAuth 2.0 |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | No | GitHub OAuth App |
| `RECAPTCHA_SITE_KEY` / `RECAPTCHA_SECRET_KEY` | No | reCAPTCHA v2 checkbox |
| `GEMINI_API_KEY` | No | Gemini LLM (backend) |
| `AZURE_OPENAI_*` | No | Azure OpenAI (backend) |

### Test Framework — `Core/.env`

| Variable | Required | Description |
|---|---|---|
| `LLM_PROVIDER` | Yes | `azure_openai` / `openai` / `anthropic` / `gemini` |
| `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_DEPLOYMENT` | If using Azure | Azure OpenAI credentials |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI key |
| `ANTHROPIC_API_KEY` | If using Anthropic | Anthropic key |
| `GEMINI_API_KEY` | If using Gemini | Gemini key |
| `GOOGLE_TEST_USERNAME` / `GOOGLE_TEST_PASSWORD` | OAuth tests only | Google test account |
| `GITHUB_TEST_USERNAME` / `GITHUB_TEST_PASSWORD` | OAuth tests only | GitHub test account |
