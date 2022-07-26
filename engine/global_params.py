# Global parameters
DEBUG = True
POLLING_BASED = True

# Bot parameters
TOKEN = <Telegram bot token>

# SQLite3 parameters
DB_NAME = <path to initialized SQLite3 database>

# Polling params
POLL_INTERVAL = <seconds, how often to poll Telegram for updates>

# Web params
DNS_NAME = <public host name>
LISTEN_IP = <IP address to listen to>
PRIVATE_KEY = <path to certificate private key>
CERTIFICATE = <path to certificate>

# Telegram webhook parameters
TG_PORT = <TCP port to start Telegram listener on>

# uvicorn parameters
UVICORN_PORT = <TCP port to start FastAPI on>

# Google API params
CLIENT_SECRET = "gcalbot.json"
REDIRECT_URL = f"https://{DNS_NAME}:{UVICORN_PORT}/oauth2callback"
