import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[3]
DEPLOYMENT = os.environ.get("HRIS_DEPLOYMENT", "").strip().lower()
if DEPLOYMENT != "render":
    load_dotenv(BASE_DIR / ".env.local", override=False, interpolate=False)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
POSTGRES_EXPECTED_HOSTNAME = os.environ.get(
    "HRIS_POSTGRES_EXPECTED_HOSTNAME", ""
).strip()
POSTGRES_EXPECTED_DATABASE = os.environ.get(
    "HRIS_POSTGRES_EXPECTED_DATABASE", ""
).strip()
POSTGRES_SSLROOTCERT = os.environ.get("HRIS_POSTGRES_SSLROOTCERT", "").strip()
DATABASE_PATH = Path(os.environ.get(
    "HRIS_DATABASE_PATH", Path.home() / ".suryanesia-hris" / "hris.sqlite3"
)).resolve()
HOST = os.environ.get("HRIS_HOST", "127.0.0.1")
PORT = int(os.environ.get("HRIS_PORT", "8000"))
