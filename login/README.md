# CS458 Project 1 – ARES

Autonomous Self-Healing Authentication & Adaptive Security

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running

## Quick Start

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd CS458-Project-1

# 2. Copy the environment file and edit if needed
cp .env.example .env

# 3. Build and start all services
docker compose up --build
```

Once running, open **http://localhost:8080** in your browser.

## OAuth Login Setup

### Google OAuth 2.0

Set in `.env`:
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

Authorized redirect URI:
- `http://localhost:8080/api/login/google/callback`

### GitHub OAuth App

Set in `.env`:
- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`

Authorization callback URL:
- `http://localhost:8080/api/login/github/callback`

Notes:
- GitHub login uses OAuth app credentials (Client ID + Client Secret), not a generic API key.
- If user email is private on GitHub, the app requests `user:email` scope and uses verified email from the email API.

## Google reCAPTCHA Challenge

ARES supports Google reCAPTCHA v2 checkbox for challenged login attempts.

1. Create keys in Google reCAPTCHA Admin Console (type: **Checkbox v2**).
2. Add these values to `.env`:
   - `RECAPTCHA_SITE_KEY`
   - `RECAPTCHA_SECRET_KEY`
3. Restart services:

```bash
docker compose up --build
```

Behavior:
- If both variables are set, reCAPTCHA is required only on `/index.html` when the account is in `challenged` state.
- Signup (`/signup.html`) does not require reCAPTCHA.
- If either value is missing, reCAPTCHA is disabled and forms work as before.

## Services

| Service    | URL                              | Description                        |
|------------|----------------------------------|------------------------------------|
| Frontend   | http://localhost:8080            | Nginx – serves HTML/CSS/JS         |
| Backend    | http://localhost:8080/api/health | Flask – through Nginx proxy        |
| Backend    | http://localhost:5001/api/health | Flask – direct access (debug only) |
| PostgreSQL | localhost:5433                   | Database                           |

## Useful Commands

```bash
# Start in background (detached mode)
docker compose up --build -d

# Stop all services
docker compose down

# View logs
docker compose logs -f

# View logs for a specific service
docker compose logs -f backend

# Rebuild only the backend
docker compose up --build backend

# Check which containers are running
docker compose ps
```

## Project Structure

```
CS458-Project-1/
├── docker-compose.yml       # Orchestrates all 3 containers
├── .env.example             # Environment variable template
├── frontend/
│   ├── Dockerfile           # Nginx image build
│   ├── nginx.conf           # Routes / to static files, /api/* to Flask
│   └── index.html           # Login page
└── backend/
    ├── Dockerfile           # Python image build
    ├── requirements.txt     # Python dependencies
    └── app.py               # Flask application
```
