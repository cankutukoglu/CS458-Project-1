import os

# LLM Provider Configuration - Azure OpenAI takes priority
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY", "").strip()
RECAPTCHA_SECRET_KEY = os.environ.get("RECAPTCHA_SECRET_KEY", "").strip()
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

# Account statuses
ACCOUNT_ACTIVE = "active"
ACCOUNT_CHALLENGED = "challenged"
ACCOUNT_LOCKED = "locked"
ACCOUNT_SUSPENDED = "suspended"

# Risk thresholds
RISK_LOW = 20
RISK_MEDIUM = 40
RISK_HIGH = 60
RISK_CRITICAL = 90

# Velocity / lock settings
VELOCITY_WINDOW_SECONDS = 300
VELOCITY_MAX_ATTEMPTS = 8
LOCK_DURATION_SECONDS = 15  # First offence: temporary lock; second offence: permanent suspension

# Each wrong password adds this many points to the risk score.
SCORE_PER_FAILED_ATTEMPT = 12
