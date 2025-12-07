import os
from pathlib import Path


def load_env_file(path: str = ".env"):
    """Minimal .env loader (no external deps)."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


# Load variables from .env if present
load_env_file()

# --- Backend API Configuration ---
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8080/')
API_VERSION = os.getenv('API_VERSION', 'api/v1')
API_TOKEN = os.getenv('API_TOKEN', 'YOUR_API_TOKEN')

# --- Telethon Configuration ---
# Replace with your actual credentials from my.telegram.org
API_ID = int(os.getenv('API_ID', '31709009'))
API_HASH = os.getenv('API_HASH', 'cc83fff2aefcc684c1aa20df23b2b639')
SESSION_NAME = os.getenv('SESSION_NAME', 'medical_assistant_session')

# --- Gemini Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY',)
# --- Groq Configuration ---
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')

HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json'
}
