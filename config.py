import os
from pathlib import Path
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Base Directory
BASE_DIR = Path(__file__).resolve().parent

# Bot Token
POLLINATIONS_BOT_TOKEN = os.getenv("POLLINATIONS_BOT_TOKEN", "").strip()

# Admin / Owner ID
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Supported Models with labels
AVAILABLE_MODELS = {
    "flux": "Flux (Highest Quality & Realism)",
    "turbo": "Turbo (Super Fast)",
    "sana": "Sana (Lightweight & Creative)"
}
DEFAULT_MODEL = "flux"

# Supported Aspect Ratios & Resolutions
AVAILABLE_RATIOS = {
    "1:1": {"width": 1024, "height": 1024, "label": "Square (1:1)"},
    "9:16": {"width": 768, "height": 1024, "label": "Portrait / Story (9:16)"},
    "16:9": {"width": 1024, "height": 768, "label": "Landscape (16:9)"},
    "4:5": {"width": 816, "height": 1020, "label": "Social Post (4:5)"},
}
DEFAULT_RATIO = "1:1"

# Directories
TEMP_PATH = BASE_DIR / "temp"
LOGS_PATH = BASE_DIR / "logs"

TEMP_PATH.mkdir(parents=True, exist_ok=True)
LOGS_PATH.mkdir(parents=True, exist_ok=True)

# Logging Level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
