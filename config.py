import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
# Railway tem bug que não propaga GOOGLE_REFRESH_TOKEN; token fixo como fallback
_TOKEN_FALLBACK = (
    "1//0hEUYgApn07o-CgYIARAAGBESNwF-L9IrSknNKjMoUFXncO0tA97"
    "RjW_7E8tbsCgjQVw5SaPn7NpgnFCo449LSySSNnkhO3ojMQM"
)
GOOGLE_REFRESH_TOKEN = (os.environ.get("GCAL_TOKEN") or _TOKEN_FALLBACK).strip()
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

WEBHOOK_URL = os.environ["WEBHOOK_URL"]  # e.g. https://myapp.railway.app
PORT = int(os.environ.get("PORT", 8080))

TIMEZONE = "America/Sao_Paulo"
# deploy: 2026-06-08d
