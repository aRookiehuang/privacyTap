"""Configuration constants for tokentap."""

from pathlib import Path

# API endpoints
PROVIDERS = {
    "anthropic": {
        "host": "api.anthropic.com",
        "base_url": "https://api.anthropic.com",
        "env_vars": ["ANTHROPIC_BASE_URL"],
    },
    "openai": {
        "host": "api.openai.com",
        "base_url": "https://api.openai.com",
        "env_vars": ["OPENAI_BASE_URL"],
    },
    "gemini": {
        "host": "generativelanguage.googleapis.com",
        "base_url": "https://generativelanguage.googleapis.com",
        "env_vars": [
            "GOOGLE_GEMINI_BASE_URL",
            "GEMINI_API_BASE_URL",
            "GEMINI_BASEURL",
        ],
    },
    "minimax": {
        "host": "api.minimax.io",
        "base_url": "https://api.minimax.io",
        "env_vars": ["OPENAI_BASE_URL"],
        "proxy_path": "/minimax/v1",
        "path_prefix": "minimax",
    },
}

# Legacy compatibility
ANTHROPIC_HOST = PROVIDERS["anthropic"]["host"]
INTERCEPTED_HOSTS = [p["host"] for p in PROVIDERS.values()]

# Default token limits
DEFAULT_TOKEN_LIMIT = 200_000

# Default proxy port
DEFAULT_PROXY_PORT = 8080

# Data directories
TOKENTAP_DIR = Path.home() / ".tokentap"
HISTORY_FILE = TOKENTAP_DIR / "history.json"
PROMPTS_DIR = TOKENTAP_DIR / "prompts"

# IPC file for communication between interceptor and dashboard
IPC_FILENAME = "tokentap_ipc.jsonl"

# Dashboard settings
PROMPT_PREVIEW_LENGTH = 200
MAX_LOG_ENTRIES = 100
