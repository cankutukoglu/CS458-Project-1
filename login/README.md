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

## Services

| Service    | URL                              | Description                  |
|------------|----------------------------------|------------------------------|
| Frontend   | http://localhost:8080             | Nginx – serves HTML/CSS/JS   |
| Backend    | http://localhost:8080/api/health  | Flask – through Nginx proxy   |
| PostgreSQL | localhost:5433                    | Database                      |

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
