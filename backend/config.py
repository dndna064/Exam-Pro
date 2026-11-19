import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

class Config:
    SECRET_KEY         = os.getenv("SECRET_KEY", "dev-secret-change-me")
    JWT_SECRET_KEY      = os.getenv("JWT_SECRET_KEY", "jwt-dev-secret")
    JWT_EXPIRES_HOURS   = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_HOURS", 8))
    DATABASE_PATH       = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "database", "examguard.db"))
    FRONTEND_URL        = os.getenv("FRONTEND_URL", "http://localhost:3000")
    JUDGE0_URL          = os.getenv("JUDGE0_URL", "https://judge0-ce.p.rapidapi.com")
    JUDGE0_API_KEY       = os.getenv("JUDGE0_API_KEY", "")
    CODE_TIMEOUT_SECS   = int(os.getenv("CODE_TIMEOUT_SECS", 10))
    CODE_MEMORY_LIMIT    = int(os.getenv("CODE_MEMORY_LIMIT_KB", 262144))
    MAX_TAB_VIOLATIONS   = int(os.getenv("MAX_TAB_VIOLATIONS", 1))
    MAX_FULLSCREEN_VIOLATIONS = int(os.getenv("MAX_FULLSCREEN_VIOLATIONS", 1))
    GEMINI_OCR_API_KEY   = os.getenv("GEMINI_OCR_API_KEY", "")
    GEMINI_EVAL_API_KEY  = os.getenv("GEMINI_EVAL_API_KEY", "")
    GEMINI_MODEL         = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    _raw_upload = os.getenv("UPLOAD_FOLDER")
    if _raw_upload:
        if os.path.isabs(_raw_upload):
            UPLOAD_FOLDER = _raw_upload
        else:
            _base = os.path.dirname(os.path.abspath(__file__))
            _clean = _raw_upload.replace("backend/", "").replace("backend\\", "")
            UPLOAD_FOLDER = os.path.abspath(os.path.join(_base, _clean))
    else:
        UPLOAD_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads"))
