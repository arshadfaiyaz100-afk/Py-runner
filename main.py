import os
import re
import ast
import time
import sys
import subprocess
import threading
import base64
import py_compile
import requests
import zipfile
import shutil
import socket
import random
import importlib.util
try:
    import importlib.metadata as importlib_metadata
except ImportError:
    importlib_metadata = None
import json
import asyncio
import signal
import hashlib
import hmac
import tempfile
import logging
import platform
import socket
import collections
import queue
import traceback
import math
import uuid
import secrets
import platform as _platform

try:
    import resource
except ImportError:
    resource = None
from pathlib import Path
from dataclasses import dataclass, field
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple, List

try:
    from packaging.requirements import Requirement as PackagingRequirement
    from packaging.utils import canonicalize_name as canonicalize_package_name
    PACKAGING_AVAILABLE = True
except ImportError:
    PackagingRequirement = None
    PACKAGING_AVAILABLE = False
    def canonicalize_package_name(name):
        return re.sub(r"[-_.]+", "-", str(name).strip()).lower()

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    Fernet = None
    InvalidToken = Exception
    PBKDF2HMAC = None
    hashes = None
    CRYPTO_AVAILABLE = False

from flask import Flask, jsonify, Response, request
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

try:
    import psutil
except ImportError:
    psutil = None

try:
    from pyrogram import Client
    MTPROTO_AVAILABLE = True
except ImportError:
    Client = None
    MTPROTO_AVAILABLE = False


# ============================================================
# CONFIGURATION
# ============================================================

ADMIN_ID = 7193432903
BOT_TOKEN = "8483068207:AAEq3LPHIYlug4qtQnkc9dQB2u-r6kQm1cs"
GLOBAL_API_ID = 29387151
GLOBAL_API_HASH = "1d70091141dda904d82684938d444473"

GH_TOKEN = os.environ.get("GH_TOKEN", "").strip()
GH_REPO = "my-hosted-bots"

PORT = int(os.environ.get("PORT", "10000"))
MAX_BOT_RAM_BYTES = int(
    os.environ.get(
        "MAX_BOT_RAM_BYTES",
        str(2 * 1024 * 1024 * 1024),
    )
)

MAX_LOG_BYTES = int(
    os.environ.get(
        "MAX_LOG_BYTES",
        str(25 * 1024 * 1024),
    )
)

MAX_VERSIONS_PER_BOT = int(
    os.environ.get("MAX_VERSIONS_PER_BOT", "10")
)

CACHE_MAX_ITEMS = int(
    os.environ.get("CACHE_MAX_ITEMS", "512")
)

CACHE_TTL_SECONDS = int(
    os.environ.get("CACHE_TTL_SECONDS", "300")
)

DEPLOYMENT_WORKERS = int(
    os.environ.get("DEPLOYMENT_WORKERS", "2")
)

# Advanced runtime controls. Existing behavior remains available; these
# features add isolation, live telemetry, and safer resource governance.
ISOLATED_BOT_ENVS = os.environ.get("ISOLATED_BOT_ENVS", "1").lower() not in {"0", "false", "no", "off"}
LIVE_HUD_UPDATE_SECONDS = float(os.environ.get("LIVE_HUD_UPDATE_SECONDS", "1.2"))
PIP_INSTALL_TIMEOUT = int(os.environ.get("PIP_INSTALL_TIMEOUT", "1800"))
STARTUP_HEALTH_TIMEOUT = float(os.environ.get("STARTUP_HEALTH_TIMEOUT", "12"))
MAX_DEPENDENCY_COUNT = int(os.environ.get("MAX_DEPENDENCY_COUNT", "250"))
MAX_BOT_PROCESSES = int(os.environ.get("MAX_BOT_PROCESSES", "64"))
MAX_BOT_THREADS = int(os.environ.get("MAX_BOT_THREADS", "256"))
MAX_BOT_CONNECTIONS = int(os.environ.get("MAX_BOT_CONNECTIONS", "512"))

AUTO_RESTART_LIMIT = int(
    os.environ.get("AUTO_RESTART_LIMIT", "3")
)

AUTO_RESTART_WINDOW = int(
    os.environ.get("AUTO_RESTART_WINDOW", "900")
)

# ============================================================
# XX V2 HARDENING / OBSERVABILITY CONTROLS
# ============================================================
MAX_BOT_CPU_PERCENT = float(os.environ.get("MAX_BOT_CPU_PERCENT", "95"))
CPU_LIMIT_STRIKES = int(os.environ.get("CPU_LIMIT_STRIKES", "4"))
MAX_BOT_DISK_BYTES = int(os.environ.get("MAX_BOT_DISK_BYTES", str(5 * 1024 * 1024 * 1024)))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
MAX_PROJECT_FILES = int(os.environ.get("MAX_PROJECT_FILES", "5000"))
AUDIT_LOG_FILE = os.environ.get("AUDIT_LOG_FILE", os.path.join(BASE_DIR if "BASE_DIR" in globals() else os.getcwd(), "audit.jsonl"))
HEALTH_API_KEY = os.environ.get("HEALTH_API_KEY", "").strip()
HOST_ENV_ALLOWLIST = {x.strip() for x in os.environ.get("HOST_ENV_ALLOWLIST", "PATH,LANG,LC_ALL,LC_CTYPE,TZ,HOME,TMP,TEMP,PORT").split(",") if x.strip()}
PROTECTED_ENV_KEYS = {"BOT_TOKEN", "GH_TOKEN", "API_HASH", "ADMIN_ID", "GH_REPO", "HEALTH_API_KEY"}
ALLOW_GLOBAL_API_CREDENTIALS = os.environ.get("ALLOW_GLOBAL_API_CREDENTIALS", "0").lower() in {"1", "true", "yes", "on"}

# Per-bot runtime isolation/security policy.  "process" preserves compatibility;
# "docker" requires a real container boundary; "required" refuses unsafe fallback.
SANDBOX_MODE = os.environ.get("SANDBOX_MODE", "process").strip().lower()
if SANDBOX_MODE not in {"process", "docker", "required"}:
    raise RuntimeError("SANDBOX_MODE must be process, docker, or required.")
DOCKER_IMAGE = os.environ.get("DOCKER_IMAGE", "python:3.12-slim")
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "none")
DOCKER_INSTALL_NETWORK = os.environ.get("DOCKER_INSTALL_NETWORK", "bridge")
DOCKER_VENV_VOLUME_PREFIX = os.environ.get("DOCKER_VENV_VOLUME_PREFIX", "xx_bot_venv")
DOCKER_PIDS_LIMIT = int(os.environ.get("DOCKER_PIDS_LIMIT", "128"))
DOCKER_MEMORY_LIMIT = os.environ.get("DOCKER_MEMORY_LIMIT", "2g")
DOCKER_CPU_LIMIT = os.environ.get("DOCKER_CPU_LIMIT", "2.0")
MAX_ENV_BYTES = int(os.environ.get("MAX_ENV_BYTES", "65536"))
MAX_SOURCE_TEXT_BYTES = int(os.environ.get("MAX_SOURCE_TEXT_BYTES", str(10 * 1024 * 1024)))
SECRET_MASTER_KEY = os.environ.get("XX_SECRET_MASTER_KEY", "").strip()
ENCRYPT_SECRETS_AT_REST = os.environ.get("ENCRYPT_SECRETS_AT_REST", "1").lower() not in {"0", "false", "no", "off"}
SECURITY_SCAN_STRICT = os.environ.get("SECURITY_SCAN_STRICT", "0").lower() not in {"0", "false", "no", "off"}
RESOURCE_GUARD_STRIKES = collections.defaultdict(int)


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is not configured. Set BOT_TOKEN in the environment."
    )


# ============================================================
# APPLICATION OBJECTS
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    threaded=True,
    num_threads=32,
)

app = Flask(__name__)

# ============================================================
# TELEGRAM TRANSPORT / RENDER WEBHOOK
# ============================================================

IS_RENDER = bool(
    os.environ.get("RENDER")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    or os.environ.get("RENDER_SERVICE_ID")
)

def _public_base_url():
    explicit = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    external = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if external:
        return external
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if hostname:
        return (
            hostname.rstrip("/")
            if hostname.startswith(("http://", "https://"))
            else "https://" + hostname
        )
    return ""

WEBHOOK_SECRET = hashlib.sha256(BOT_TOKEN.encode("utf-8")).hexdigest()
WEBHOOK_PATH = "/telegram/webhook"
WEBHOOK_URL = ""
_telegram_transport_configured = False
_telegram_transport_lock = threading.Lock()

def configure_telegram_transport():
    """Use exactly one Telegram update transport per running board."""
    global WEBHOOK_URL, _telegram_transport_configured

    with _telegram_transport_lock:
        if _telegram_transport_configured:
            return "already-configured"

        if IS_RENDER:
            base = _public_base_url()
            if not base:
                raise RuntimeError(
                    "Render detected but no public URL is available. "
                    "Set PUBLIC_BASE_URL to the Render HTTPS URL."
                )

            WEBHOOK_URL = base + WEBHOOK_PATH
            bot.remove_webhook()
            time.sleep(0.5)

            ok = bot.set_webhook(
                url=WEBHOOK_URL,
                secret_token=WEBHOOK_SECRET,
                drop_pending_updates=True,
            )
            if ok is False:
                raise RuntimeError("Telegram webhook setup returned False.")

            _telegram_transport_configured = True
            logger.info(
                "Telegram transport: WEBHOOK ACTIVE | %s",
                WEBHOOK_URL,
            )
            return "webhook"

        _telegram_transport_configured = True
        logger.info("Telegram transport: LOCAL POLLING MODE")
        return "polling"

def start_local_polling_once():
    """Local-only polling fallback with a per-process duplicate-thread guard."""
    if IS_RENDER:
        logger.warning(
            "Local polling request ignored: Render webhook mode is active."
        )
        return None

    existing = getattr(start_local_polling_once, "_thread", None)
    if existing is not None and existing.is_alive():
        return existing

    def _run():
        try:
            bot.infinity_polling(
                timeout=10,
                long_polling_timeout=5,
                skip_pending=True,
                allowed_updates=None,
            )
        except Exception:
            logger.exception("Telegram polling stopped unexpectedly.")

    thread = threading.Thread(
        target=_run,
        name="telegram-polling",
        daemon=True,
    )
    thread.start()
    start_local_polling_once._thread = thread
    logger.info("Telegram local polling: ACTIVE")
    return thread

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    if not IS_RENDER:
        return jsonify({"error": "webhook disabled in local mode"}), 404

    supplied_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        "",
    )
    if not hmac.compare_digest(
        supplied_secret,
        WEBHOOK_SECRET,
    ):
        return jsonify({"error": "forbidden"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid update"}), 400

    try:
        update = telebot.types.Update.de_json(
            json.dumps(payload)
        )
        bot.process_new_updates([update])
    except Exception:
        logger.exception(
            "Telegram webhook update processing failed."
        )
        return jsonify({"ok": False}), 200

    return jsonify({"ok": True}), 200


BASE_DIR = os.path.abspath(os.getcwd())

HOST_DIR = os.path.join(BASE_DIR, "hosted_env")
LOG_DIR = os.path.join(BASE_DIR, "logs")
TEMP_DIR = os.path.join(BASE_DIR, "temp_uploads")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
VERSION_DIR = os.path.join(BASE_DIR, "versions")

REGISTRY_FILE = os.path.join(BASE_DIR, "registry.json")
REGISTRY_TMP_FILE = os.path.join(BASE_DIR, "registry.json.tmp")
REGISTRY_BACKUP_FILE = os.path.join(BASE_DIR, "registry.json.bak")
AUDIT_LOG_FILE = os.environ.get("AUDIT_LOG_FILE", os.path.join(BASE_DIR, "audit.jsonl"))
SECURITY_DIR = os.path.join(BASE_DIR, "security")
MANIFEST_DIR = os.path.join(BASE_DIR, "manifests")
for _d in (SECURITY_DIR, MANIFEST_DIR):
    os.makedirs(_d, exist_ok=True)
ENGINE_LOCK_FILE = os.path.join(BASE_DIR, ".engine.lock")

for directory in (
    HOST_DIR,
    LOG_DIR,
    TEMP_DIR,
    BACKUP_DIR,
    VERSION_DIR,
):
    os.makedirs(directory, exist_ok=True)


# ============================================================
# GLOBAL STATE
# ============================================================

hosted_processes: Dict[str, Dict[str, Any]] = {}
user_deploy_states: Dict[str, Dict[str, Any]] = {}

user_chats = set()
banned_users = set()
user_custom_envs: Dict[str, Dict[str, str]] = {}
# Explicit per-bot runtime secrets/configuration. Never inject the entire user store.
bot_envs: Dict[str, Dict[str, str]] = {}
# Host/system dependency manager. This is intentionally separate from per-bot venvs.
system_requirements_catalog: Dict[str, Dict[str, Any]] = {}
system_requirements_lock = threading.RLock()

bot_metadata: Dict[str, Dict[str, Any]] = {}
bot_versions: Dict[str, List[Dict[str, Any]]] = {}
bot_metrics: Dict[str, Dict[str, Any]] = {}
bot_locks: Dict[str, threading.RLock] = {}

restart_history: Dict[str, collections.deque] = {}

engine_start_time = time.time()

MAINTENANCE_MODE = False
SHUTDOWN_REQUESTED = False

registry_lock = threading.RLock()
state_lock = threading.RLock()

DEPLOYMENT_QUEUE_MAX_ITEMS = int(os.environ.get("DEPLOYMENT_QUEUE_MAX_ITEMS", "64"))
if DEPLOYMENT_QUEUE_MAX_ITEMS <= 0:
    raise RuntimeError("DEPLOYMENT_QUEUE_MAX_ITEMS must be positive.")
deployment_queue = queue.Queue(maxsize=DEPLOYMENT_QUEUE_MAX_ITEMS)
deployment_workers = []
deployment_queue_lock = threading.RLock()
deployment_queue_keys = set()

# Live deployment telemetry keyed by bot id. This is intentionally kept
# separate from the persistent registry so secrets and transient logs do not
# get written to disk.
deployment_runtime: Dict[str, Dict[str, Any]] = {}
deployment_runtime_lock = threading.RLock()

ENGINE_LOCK_HANDLE = None


# ============================================================
# PACKAGE MAP
# ============================================================

PIP_MAP = {
    "telebot": "pyTelegramBotAPI",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "crypto": "pycryptodome",
    "sklearn": "scikit-learn",
    "telegram": "python-telegram-bot",
    "discord": "discord.py",
    "pyrogram": "pyrogram tgcrypto",
    "aiogram": "aiogram",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "jose": "python-jose",
    "jwt": "PyJWT",
    "pydantic": "pydantic",
    "torch": "torch",
    "tensorflow": "tensorflow",
    "requests": "requests",
    "flask": "Flask",
}

BUILTINS = set(sys.builtin_module_names)

STANDARD_LIBRARY = {
    "abc",
    "argparse",
    "asyncio",
    "ast",
    "base64",
    "collections",
    "contextlib",
    "copy",
    "csv",
    "datetime",
    "email",
    "enum",
    "functools",
    "gc",
    "glob",
    "hashlib",
    "http",
    "importlib",
    "inspect",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "multiprocessing",
    "os",
    "pathlib",
    "pickle",
    "platform",
    "queue",
    "random",
    "re",
    "secrets",
    "shlex",
    "shutil",
    "signal",
    "socket",
    "sqlite3",
    "statistics",
    "string",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "time",
    "traceback",
    "typing",
    "uuid",
    "zipfile",
}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("XX_ENGINE")


# ============================================================
# SINGLE ENGINE INSTANCE
# ============================================================

def acquire_engine_lock():
    """
    Prevent two copies of the main hosting engine from running.
    """

    global ENGINE_LOCK_HANDLE

    if os.name == "nt":
        import msvcrt

        ENGINE_LOCK_HANDLE = open(
            ENGINE_LOCK_FILE,
            "a+",
            encoding="utf-8",
        )

        try:
            msvcrt.locking(
                ENGINE_LOCK_HANDLE.fileno(),
                msvcrt.LK_NBLCK,
                1,
            )
        except OSError:
            raise RuntimeError(
                "Another hosting engine instance is already running."
            )

    else:
        import fcntl

        ENGINE_LOCK_HANDLE = open(
            ENGINE_LOCK_FILE,
            "a+",
            encoding="utf-8",
        )

        try:
            fcntl.flock(
                ENGINE_LOCK_HANDLE.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except OSError:
            raise RuntimeError(
                "Another hosting engine instance is already running."
            )

    ENGINE_LOCK_HANDLE.seek(0)
    ENGINE_LOCK_HANDLE.truncate()
    ENGINE_LOCK_HANDLE.write(str(os.getpid()))
    ENGINE_LOCK_HANDLE.flush()


def release_engine_lock():
    global ENGINE_LOCK_HANDLE

    if ENGINE_LOCK_HANDLE is None:
        return

    try:
        if os.name == "nt":
            import msvcrt

            ENGINE_LOCK_HANDLE.seek(0)

            try:
                msvcrt.locking(
                    ENGINE_LOCK_HANDLE.fileno(),
                    msvcrt.LK_UNLCK,
                    1,
                )
            except OSError:
                pass

        else:
            import fcntl

            try:
                fcntl.flock(
                    ENGINE_LOCK_HANDLE.fileno(),
                    fcntl.LOCK_UN,
                )
            except OSError:
                pass

        ENGINE_LOCK_HANDLE.close()

    except Exception:
        logger.exception("Failed to release engine lock.")

    ENGINE_LOCK_HANDLE = None


# ============================================================
# TTL/LRU CACHE
# ============================================================

class TTLCache:

    def __init__(
        self,
        max_items: int = CACHE_MAX_ITEMS,
        ttl: int = CACHE_TTL_SECONDS,
    ):
        self.max_items = max_items
        self.ttl = ttl
        self.data = collections.OrderedDict()
        self.lock = threading.RLock()

    def _expired(self, item):
        return time.time() >= item["expires"]

    def get(self, key, default=None):
        with self.lock:
            item = self.data.get(key)

            if item is None:
                return default

            if self._expired(item):
                self.data.pop(key, None)
                return default

            self.data.move_to_end(key)

            return item["value"]

    def set(self, key, value, ttl=None):
        with self.lock:
            self.data[key] = {
                "value": value,
                "expires": time.time()
                + (self.ttl if ttl is None else ttl),
            }

            self.data.move_to_end(key)

            while len(self.data) > self.max_items:
                self.data.popitem(last=False)

    def delete(self, key):
        with self.lock:
            self.data.pop(key, None)

    def clear(self):
        with self.lock:
            self.data.clear()

    def cleanup(self):
        with self.lock:
            expired = [
                key
                for key, item in self.data.items()
                if self._expired(item)
            ]

            for key in expired:
                self.data.pop(key, None)


status_cache = TTLCache()


# ============================================================
# RETRY MANAGER
# ============================================================

def retry_operation(
    operation,
    attempts=4,
    base_delay=1.0,
    max_delay=20.0,
    exceptions=(Exception,),
):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()

        except exceptions as exc:
            last_error = exc

            if attempt >= attempts:
                break

            delay = min(
                max_delay,
                base_delay * (2 ** (attempt - 1)),
            )

            delay += random.uniform(
                0,
                max(0.1, delay * 0.25),
            )

            time.sleep(delay)

    raise last_error


# ============================================================
# GENERAL UTILITIES
# ============================================================

def is_admin(user_id):
    try:
        return int(user_id) == ADMIN_ID
    except Exception:
        return False


def is_banned(user_id):
    return int(user_id) in banned_users


def get_bot_lock(bot_id):
    with state_lock:
        if bot_id not in bot_locks:
            bot_locks[bot_id] = threading.RLock()

        return bot_locks[bot_id]


def get_readable_size(size_bytes):

    if size_bytes <= 0:
        return "0B"

    units = (
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    )

    index = int(
        math.floor(
            math.log(size_bytes, 1024)
        )
    )

    index = min(index, len(units) - 1)

    value = size_bytes / (
        1024 ** index
    )

    return f"{round(value, 2)} {units[index]}"


def get_readable_uptime(seconds):

    mins, secs = divmod(
        int(seconds),
        60,
    )

    hours, mins = divmod(
        mins,
        60,
    )

    days, hours = divmod(
        hours,
        24,
    )

    return (
        f"{days}d "
        f"{hours}h "
        f"{mins}m "
        f"{secs}s"
    )


def get_progress_bar(percent, length=10):

    percent = max(
        0,
        min(100, float(percent)),
    )

    filled = int(
        (percent / 100) * length
    )

    return (
        "█" * filled
        + "░" * (length - filled)
    )


def redact_sensitive_text(value, maximum=3000):
    text = str(value)
    for key, val in os.environ.items():
        if SENSITIVE_KEY_RE.search(key) and val:
            text = text.replace(val, "***REDACTED***")
    for store in list(user_custom_envs.values()) + list(bot_envs.values()):
        for val in store.values():
            if val:
                text = text.replace(str(val), "***REDACTED***")
    return safe_text(text, maximum)

def safe_text(value, maximum=3000):
    value = str(value)

    if len(value) > maximum:
        return value[:maximum] + "..."

    return value


def now_iso():
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(),
    )


# ============================================================
# ATOMIC REGISTRY
# ============================================================

def _secret_fernet():
    if not ENCRYPT_SECRETS_AT_REST:
        return None
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography is required for encrypted secret storage.")
    material = (SECRET_MASTER_KEY or BOT_TOKEN).encode("utf-8")
    if not material:
        raise RuntimeError("No secret master material is available.")
    salt = hashlib.sha256(b"XX-PROMAX-SECRET-SALT-v1").digest()[:16]
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(material)))

def _protect_registry_secrets(data):
    if not ENCRYPT_SECRETS_AT_REST:
        return data
    f = _secret_fernet()
    payload = {"envs": data.get("envs", {}), "bot_envs": data.get("bot_envs", {})}
    token = f.encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
    data = dict(data)
    data["envs"] = {}
    data["bot_envs"] = {}
    data["secret_store"] = {"version": 1, "ciphertext": token}
    return data

def _unprotect_registry_secrets(data):
    store = data.get("secret_store")
    if store and store.get("ciphertext"):
        f = _secret_fernet()
        try:
            payload = json.loads(f.decrypt(store["ciphertext"].encode("ascii")))
        except Exception as exc:
            raise RuntimeError("Encrypted secret store could not be decrypted.") from exc
        data = dict(data)
        data["envs"] = payload.get("envs", {})
        data["bot_envs"] = payload.get("bot_envs", {})
        return data
    # Legacy plaintext registries are readable for migration, but are never
    # written back unencrypted once encryption is enabled.
    return data

def registry_snapshot():

    with state_lock:
        bots = {}

        for bot_id, data in hosted_processes.items():

            process = data.get("process")

            running = (
                process is not None
                and process.poll() is None
            )

            bots[bot_id] = {
                "owner_id": data.get("owner_id"),
                "entry_file": data.get("entry_file"),
                "running": running,
                "pid": (
                    process.pid
                    if process is not None
                    else None
                ),
                "log_file": data.get("log_file"),
                "start_time": data.get(
                    "start_time",
                    time.time(),
                ),
            }

    return _protect_registry_secrets({
        "version": 4,
        "saved_at": now_iso(),
        "bots": bots,
        "envs": user_custom_envs,
        "bot_envs": bot_envs,
        "system_requirements": system_requirements_catalog,
        "chats": list(user_chats),
        "banned_users": list(banned_users),
        "maintenance": MAINTENANCE_MODE,
        "metadata": bot_metadata,
        "versions": bot_versions,
        "metrics": bot_metrics,
    })


def save_registry():

    data = registry_snapshot()

    with registry_lock:

        try:
            if os.path.exists(REGISTRY_FILE):
                shutil.copy2(
                    REGISTRY_FILE,
                    REGISTRY_BACKUP_FILE,
                )

            with open(
                REGISTRY_TMP_FILE,
                "w",
                encoding="utf-8",
            ) as handle:

                json.dump(
                    data,
                    handle,
                    indent=4,
                    ensure_ascii=False,
                )

                handle.flush()
                os.fsync(handle.fileno())

            os.replace(
                REGISTRY_TMP_FILE,
                REGISTRY_FILE,
            )

        except Exception as exc:
            logger.exception("Atomic registry save failed.")
            security_audit_event("registry_save_failed", error=type(exc).__name__)
            raise


def load_registry():
    global user_custom_envs, bot_envs, user_chats, banned_users, system_requirements_catalog
    global MAINTENANCE_MODE, bot_metadata, bot_versions, bot_metrics

    candidates = [REGISTRY_FILE, REGISTRY_BACKUP_FILE]
    last_error = None
    data = None
    source = None

    for candidate in candidates:
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                candidate_data = json.load(handle)
            candidate_data = _unprotect_registry_secrets(candidate_data)
            if not isinstance(candidate_data, dict):
                raise ValueError("Registry root must be an object.")
            data = candidate_data
            source = candidate
            break
        except Exception as exc:
            last_error = exc
            logger.exception("Registry load failed for %s.", candidate)
            security_audit_event("registry_load_failed", source=candidate, error=type(exc).__name__)

    if data is None:
        if last_error is not None:
            logger.error("No valid registry or registry backup could be loaded.")
        return False

    try:
        user_custom_envs = data.get("envs", {})
        bot_envs = data.get("bot_envs", {})
        loaded_system_requirements = data.get("system_requirements", {})
        system_requirements_catalog = loaded_system_requirements if isinstance(loaded_system_requirements, dict) else {}
        user_chats = set(data.get("chats", []))
        banned_users = set(data.get("banned_users", []))
        MAINTENANCE_MODE = bool(data.get("maintenance", False))
        bot_metadata = data.get("metadata", {})
        bot_versions = data.get("versions", {})
        bot_metrics = data.get("metrics", {})

        bots = data.get("bots", {})
        if not isinstance(bots, dict):
            raise ValueError("Registry bots field is invalid.")

        for bot_id, info in bots.items():
            if not isinstance(info, dict):
                continue
            bot_dir = os.path.abspath(os.path.join(HOST_DIR, str(bot_id)))
            try:
                if os.path.commonpath([HOST_DIR, bot_dir]) != os.path.abspath(HOST_DIR):
                    continue
            except ValueError:
                continue
            entry_file = str(info.get("entry_file") or "")
            owner_id = info.get("owner_id")
            if not entry_file or owner_id is None:
                continue
            entry_path = os.path.abspath(os.path.join(bot_dir, entry_file))
            if os.path.commonpath([bot_dir, entry_path]) != bot_dir or not os.path.isfile(entry_path):
                continue
            # Recovery is centralized through start_bot_once(), preserving duplicate-process protection.
            try:
                start_bot_once(str(bot_id), entry_file, owner_id, reason="registry_recovery", notify=False)
            except Exception:
                logger.exception("Failed to recover bot %s from registry.", bot_id)
                security_audit_event("bot_registry_recovery_failed", str(bot_id), owner_id, source=source)

        if source == REGISTRY_BACKUP_FILE:
            security_audit_event("registry_recovered_from_backup", source=source)
        return True
    except Exception as exc:
        logger.exception("Registry state application failed.")
        security_audit_event("registry_state_apply_failed", error=type(exc).__name__)
        return False


# ============================================================
# METRICS
# ============================================================

def ensure_metrics(bot_id):

    with state_lock:

        if bot_id not in bot_metrics:
            bot_metrics[bot_id] = {
                "deployments": 0,
                "starts": 0,
                "stops": 0,
                "restarts": 0,
                "crashes": 0,
                "errors": 0,
                "successful_runs": 0,
                "last_start": None,
                "last_stop": None,
                "last_restart": None,
                "last_error": None,
                "last_health_check": None,
                "peak_memory": 0,
                "created_at": now_iso(),
            }

        return bot_metrics[bot_id]


def metric_increment(
    bot_id,
    key,
    amount=1,
):

    metrics = ensure_metrics(bot_id)

    metrics[key] = (
        int(metrics.get(key, 0))
        + amount
    )


def record_error(bot_id, error):

    metrics = ensure_metrics(bot_id)

    metrics["errors"] = (
        int(metrics.get("errors", 0))
        + 1
    )

    metrics["last_error"] = safe_text(
        error,
        1000,
    )


# ============================================================
# BOT STATUS
# ============================================================

def get_process(bot_id):

    data = hosted_processes.get(
        bot_id
    )

    if not data:
        return None

    return data.get("process")


def is_bot_running(bot_id):

    process = get_process(bot_id)

    return (
        process is not None
        and process.poll() is None
    )


def get_bot_status(bot_id):

    data = hosted_processes.get(
        bot_id
    )

    if not data:
        return {
            "status": "UNKNOWN",
            "running": False,
            "pid": None,
            "uptime": "Offline",
        }

    process = data.get(
        "process"
    )

    running = (
        process is not None
        and process.poll() is None
    )

    if running:

        uptime = get_readable_uptime(
            time.time()
            - data.get(
                "start_time",
                time.time(),
            )
        )

        return {
            "status": "RUNNING",
            "running": True,
            "pid": process.pid,
            "uptime": uptime,
        }

    return {
        "status": "STOPPED",
        "running": False,
        "pid": None,
        "uptime": "Offline",
    }


# ============================================================
# PROCESS LOCK / SINGLE INSTANCE
# ============================================================

def _docker_available():
    return shutil.which("docker") is not None

def _docker_volume_name(bot_id):
    digest = hashlib.sha256(str(bot_id).encode("utf-8")).hexdigest()[:20]
    return f"{DOCKER_VENV_VOLUME_PREFIX}_{digest}"

def _docker_install_command(bot_id, package_args):
    bot_dir = Path(HOST_DIR, bot_id).resolve()
    volume = _docker_volume_name(bot_id)
    return [
        "docker", "run", "--rm", "--init",
        "--pids-limit", str(DOCKER_PIDS_LIMIT),
        "--memory", DOCKER_MEMORY_LIMIT, "--cpus", DOCKER_CPU_LIMIT,
        "--network", DOCKER_INSTALL_NETWORK,
        "-v", f"{bot_dir}:/workspace:ro",
        "-v", f"{volume}:/venv",
        "-w", "/workspace",
        DOCKER_IMAGE, "python", "-m", "pip", "install",
        "--target", "/venv/site-packages",
        *package_args,
    ]

def _docker_probe_command(bot_id, import_name):
    volume = _docker_volume_name(bot_id)
    return [
        "docker", "run", "--rm", "--init",
        "--pids-limit", str(DOCKER_PIDS_LIMIT),
        "--memory", DOCKER_MEMORY_LIMIT, "--cpus", DOCKER_CPU_LIMIT,
        "--network", "none",
        "-v", f"{volume}:/venv:ro",
        DOCKER_IMAGE, "python", "-c",
        "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)",
        import_name,
    ]

def _sandbox_command(bot_id, entry_path, runtime_python, owner_id, env_values=None):
    """Return a real container command or raise when sandbox is required."""
    if SANDBOX_MODE in {"docker", "required"} and not _docker_available():
        raise RuntimeError("Required Docker sandbox is unavailable; refusing unsafe execution.")
    if SANDBOX_MODE != "docker" and SANDBOX_MODE != "required":
        return None
    bot_dir = Path(HOST_DIR, bot_id).resolve()
    rel_entry = Path(entry_path).resolve().relative_to(bot_dir).as_posix()
    return [
        "docker", "run", "--rm", "--init",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit", str(DOCKER_PIDS_LIMIT),
        "--memory", DOCKER_MEMORY_LIMIT, "--cpus", DOCKER_CPU_LIMIT,
        "--network", DOCKER_NETWORK,
    ] + sum((["-e", f"{k}={v}"] for k, v in (env_values or {}).items() if ENV_NAME_RE.match(str(k)) and "\x00" not in str(v)), []) + [
        "-e", "PYTHONPATH=/venv/site-packages",
        "-v", f"{bot_dir}:/workspace:rw",
        "-v", f"{_docker_volume_name(bot_id)}:/venv:ro",
        "-w", "/workspace",
        DOCKER_IMAGE, "python", rel_entry,
    ]

def verify_startup_health(bot_id, timeout=None):
    timeout = STARTUP_HEALTH_TIMEOUT if timeout is None else float(timeout)
    deadline = time.monotonic() + max(0.5, timeout)
    while time.monotonic() < deadline:
        proc = get_process(bot_id)
        ok, _ = HealthVerifier.verify_process(proc)
        if ok:
            # Give the child a brief window to exit immediately after exec.
            time.sleep(0.25)
            ok2, msg2 = HealthVerifier.verify_process(get_process(bot_id))
            if ok2:
                return True, "Startup process remained healthy."
            return False, msg2
        time.sleep(0.25)
    return False, "Startup health timeout."

def start_bot_once(
    bot_id,
    entry_file,
    owner_id,
    reason="manual",
    notify=False,
    verify_startup=True,
):
    """
    Central start gate.

    This function is the only normal route used to launch a hosted bot.
    If a bot is already alive, it NEVER launches another process.
    """

    lock = get_bot_lock(bot_id)

    with lock:

        existing = hosted_processes.get(
            bot_id
        )

        if existing:

            existing_process = existing.get(
                "process"
            )

            if (
                existing_process is not None
                and existing_process.poll() is None
            ):
                response = {
                    "started": False,
                    "already_running": True,
                    "pid": existing_process.pid,
                    "message": (
                        f"🤖 `{bot_id}` is already running.\n\n"
                        f"🟢 Status: `RUNNING`\n"
                        f"🆔 PID: `{existing_process.pid}`\n"
                        f"⚠️ Duplicate process was NOT created."
                    ),
                }

                if notify:
                    try:
                        bot.send_message(
                            owner_id,
                            response["message"],
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass

                return response

        bot_dir = os.path.abspath(
            os.path.join(
                HOST_DIR,
                bot_id,
            )
        )

        entry_path = os.path.abspath(
            os.path.join(
                bot_dir,
                entry_file,
            )
        )

        if not entry_path.startswith(
            bot_dir + os.sep
        ):
            raise ValueError(
                "Invalid entry path."
            )

        if not os.path.isfile(entry_path):
            raise FileNotFoundError(
                "Entry file does not exist."
            )

        os.makedirs(
            LOG_DIR,
            exist_ok=True,
        )

        log_file_path = os.path.join(
            LOG_DIR,
            f"{bot_id}.log",
        )

        log_out = open(
            log_file_path,
            "a",
            encoding="utf-8",
        )

        # SECURITY: never pass the host's complete environment to untrusted bots.
        # Only a minimal allow-list plus the owner's explicitly stored variables
        # is inherited. Sensitive host credentials remain outside the bot process.
        custom_env = {k: v for k, v in os.environ.items() if k in HOST_ENV_ALLOWLIST}
        # SECURITY: only this bot's explicitly granted variables are injected.
        # The legacy per-user ENV store is never implicitly inherited by hosted code.
        for k, v in bot_envs.get(str(bot_id), {}).items():
            if k not in PROTECTED_ENV_KEYS and ENV_NAME_RE.match(str(k)):
                custom_env[str(k)] = str(v)

        if ALLOW_GLOBAL_API_CREDENTIALS:
            if GLOBAL_API_ID:
                custom_env["API_ID"] = str(GLOBAL_API_ID)
            if GLOBAL_API_HASH:
                custom_env["API_HASH"] = GLOBAL_API_HASH

        # Host-controlled identity cannot be overridden by user ENV values.
        custom_env["BOT_HOST_ID"] = bot_id
        custom_env["BOT_OWNER_ID"] = str(owner_id)
        custom_env["BOT_HOSTED"] = "1"

        try:

            runtime_python = sys.executable
            if ISOLATED_BOT_ENVS:
                candidate = os.path.join(bot_dir, ".venv", "Scripts" if os.name == "nt" else "bin", "python")
                if os.path.isfile(candidate):
                    runtime_python = candidate
            sandbox_cmd = _sandbox_command(bot_id, entry_path, runtime_python, owner_id, custom_env)
            command = sandbox_cmd or [runtime_python, entry_path]
            popen_kwargs = dict(
                cwd=bot_dir,
                stdout=log_out,
                stderr=log_out,
                env=custom_env,
                text=True,
            )
            if os.name != "nt":
                # New session/process group lets the watchdog terminate the
                # complete bot tree instead of leaving child processes behind.
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(
                command,
                **popen_kwargs,
            )

        except Exception as exc:

            log_out.close()

            record_error(
                bot_id,
                exc,
            )

            raise

        hosted_processes[bot_id] = {
            "process": process,
            "pid": process.pid,
            "entry_file": entry_file,
            "owner_id": owner_id,
            "start_time": time.time(),
            "log_file": log_file_path,
            "retries": 0,
            "manual_stop": False,
            "launch_reason": reason,
            "log_handle": log_out,
            "runtime_python": runtime_python,
            "isolated_env": runtime_python != sys.executable,
            "sandbox_mode": SANDBOX_MODE if sandbox_cmd else "process",
            "sandboxed": bool(sandbox_cmd),
        }

        if verify_startup:
            ok, startup_message = verify_startup_health(bot_id)
            if not ok:
                try:
                    stop_script_process(bot_id, reason="startup_health_failed")
                except Exception:
                    pass
                raise DeploymentError(f"Startup verification failed: {startup_message}")

        metadata = bot_metadata.setdefault(
            bot_id,
            {},
        )

        metadata.update(
            {
                "owner_id": owner_id,
                "entry_file": entry_file,
                "last_reason": reason,
                "last_start": now_iso(),
            }
        )

        metric_increment(
            bot_id,
            "starts",
        )
        security_audit_event("bot_started", bot_id, owner_id, reason=reason, pid=process.pid, isolated=runtime_python != sys.executable)

        ensure_metrics(
            bot_id
        )["last_start"] = now_iso()

        save_registry()

        return {
            "started": True,
            "already_running": False,
            "pid": process.pid,
            "message": (
                f"🚀 `{bot_id}` started successfully.\n"
                f"🆔 PID: `{process.pid}`"
            ),
        }


# ============================================================
# STOP PROCESS
# ============================================================

def stop_script_process(
    bot_id,
    reason="manual",
):

    lock = get_bot_lock(
        bot_id
    )

    with lock:

        data = hosted_processes.get(
            bot_id
        )

        if not data:
            return False

        process = data.get(
            "process"
        )

        data["manual_stop"] = True

        if (
            process is not None
            and process.poll() is None
        ):

            try:

                if psutil:

                    parent = psutil.Process(
                        process.pid
                    )

                    children = parent.children(
                        recursive=True
                    )

                    for child in children:

                        try:
                            child.terminate()
                        except Exception:
                            pass

                    try:
                        parent.terminate()
                        parent.wait(timeout=8)
                    except Exception:
                        try:
                            parent.kill()
                            parent.wait(timeout=4)
                        except Exception:
                            pass
                    for child in children:
                        try:
                            if child.is_running():
                                child.wait(timeout=2)
                        except Exception:
                            try:
                                child.kill()
                            except Exception:
                                pass

                else:

                    process.terminate()

                    try:
                        process.wait(
                            timeout=8
                        )
                    except subprocess.TimeoutExpired:
                        process.kill()

            except Exception as exc:

                record_error(
                    bot_id,
                    exc,
                )

                try:
                    process.kill()
                except Exception:
                    pass

        log_handle = data.get(
            "log_handle"
        )

        if log_handle:

            try:
                log_handle.flush()
                log_handle.close()
            except Exception:
                pass

        metric_increment(
            bot_id,
            "stops",
        )
        security_audit_event("bot_stopped", bot_id, data.get("owner_id"), reason=reason)

        ensure_metrics(
            bot_id
        )["last_stop"] = now_iso()

        data["stop_reason"] = reason

        save_registry()

        return True


# ============================================================
# EXPLICIT RESTART
# ============================================================

def restart_bot(
    bot_id,
    owner_id,
    notify=True,
):

    lock = get_bot_lock(
        bot_id
    )

    with lock:

        data = hosted_processes.get(
            bot_id
        )

        if not data:
            return {
                "ok": False,
                "message": (
                    f"❌ `{bot_id}` does not exist."
                ),
            }

        entry_file = data.get(
            "entry_file"
        )

        stop_script_process(
            bot_id,
            reason="explicit_restart",
        )

        time.sleep(0.5)

        result = start_bot_once(
            bot_id,
            entry_file,
            owner_id,
            reason="explicit_restart",
            notify=False,
            verify_startup=True,
        )

        if result["started"]:

            metric_increment(
                bot_id,
                "restarts",
            )

            ensure_metrics(
                bot_id
            )["last_restart"] = now_iso()

            result["message"] = (
                f"🔄 `{bot_id}` restarted successfully.\n\n"
                f"🟢 New PID: `{result['pid']}`"
            )

        if notify:

            try:
                bot.send_message(
                    owner_id,
                    result["message"],
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        save_registry()

        return result


# ============================================================
# LOG ROTATION
# ============================================================

def rotate_log_if_needed(
    bot_id,
):

    path = os.path.join(
        LOG_DIR,
        f"{bot_id}.log",
    )

    if not os.path.isfile(path):
        return

    try:

        if os.path.getsize(path) <= MAX_LOG_BYTES:
            return

        rotated = (
            f"{path}."
            f"{time.strftime('%Y%m%d_%H%M%S_%f')}"
        )

        # Hosted child processes keep their stdout file descriptor open.
        # Renaming the live file would leave the child writing into the old
        # inode while the newly-created path stays empty. Preserve the active
        # descriptor by copying the current log to the archive and truncating
        # the original file in place.
        with open(path, "rb") as source, open(rotated, "wb") as archive:
            shutil.copyfileobj(source, archive, length=1024 * 1024)
            archive.flush()
            os.fsync(archive.fileno())
        with open(path, "r+b") as active:
            active.truncate(0)
            active.flush()
            os.fsync(active.fileno())

    except Exception:
        logger.exception(
            "Log rotation failed for %s",
            bot_id,
        )


# ============================================================
# IMPORT ANALYZER
# ============================================================

def deep_analyze_imports(
    bot_folder,
):

    detected_modules = set()

    for root, _, files in os.walk(
        bot_folder
    ):

        for filename in files:

            if not filename.endswith(
                ".py"
            ):
                continue

            file_path = os.path.join(
                root,
                filename,
            )

            try:

                with open(
                    file_path,
                    "r",
                    encoding="utf-8",
                    errors="ignore",
                ) as handle:

                    tree = ast.parse(
                        handle.read()
                    )

                for node in ast.walk(tree):

                    if isinstance(
                        node,
                        ast.Import,
                    ):

                        for alias in node.names:

                            detected_modules.add(
                                alias.name.split(
                                    "."
                                )[0]
                            )

                    elif isinstance(
                        node,
                        ast.ImportFrom,
                    ):

                        if node.module:

                            detected_modules.add(
                                node.module.split(
                                    "."
                                )[0]
                            )

            except Exception:
                continue

    result = []

    for module in sorted(
        detected_modules
    ):

        if module in BUILTINS:
            continue

        if module in STANDARD_LIBRARY:
            continue

        package = PIP_MAP.get(
            module,
            module,
        )

        if package not in result:
            result.append(package)

    return result


# ============================================================
# ADVANCED LIVE DEPLOYMENT TELEMETRY
# ============================================================

def _deployment_state(bot_id):
    with deployment_runtime_lock:
        return deployment_runtime.setdefault(bot_id, {
            "stage": "Initializing",
            "action": "Starting deployment",
            "percent": 0.0,
            "package": None,
            "package_index": 0,
            "package_total": 0,
            "package_percent": None,
            "downloaded": 0,
            "total_bytes": 0,
            "speed_bps": 0.0,
            "eta_seconds": None,
            "installed": 0,
            "failed": 0,
            "pending": 0,
            "started_at": time.time(),
            "last_update": 0.0,
            "updated_at": time.time(),
            "freshness": "FRESH",
            "last_event": "Deployment initialized",
            "events": collections.deque(maxlen=18),
            "last_error": None,
        })


def _deployment_event(bot_id, event, **updates):
    state = _deployment_state(bot_id)
    now = time.time()
    with deployment_runtime_lock:
        state.update(updates)
        state["last_event"] = event
        state["events"].append(f"{time.strftime('%H:%M:%S')} | {event}")
        state["last_update"] = now
        state["updated_at"] = now
        state["freshness"] = "FRESH"
    return state


def _format_duration(seconds):
    if seconds is None or seconds < 0 or not math.isfinite(float(seconds)):
        return "calculating"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _parse_progress_line(line):
    """Best-effort parser for pip progress-bar/output variants."""
    text = line.replace("\r", " ").strip()
    percent = None
    downloaded = None
    total = None
    speed = None
    eta = None
    match = re.search(r"(\d{1,3}(?:\.\d+)?)%", text)
    if match:
        try:
            percent = max(0.0, min(100.0, float(match.group(1))))
        except ValueError:
            pass
    size_re = r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)"
    sizes = re.findall(size_re, text, re.I)
    if len(sizes) >= 2:
        def to_bytes(pair):
            value, unit = pair
            return float(value) * (1024 ** {"B":0,"KB":1,"MB":2,"GB":3,"TB":4}[unit.upper()])
        try:
            downloaded = int(to_bytes(sizes[0]))
            total = int(to_bytes(sizes[1]))
        except Exception:
            pass
    speed_match = re.search(size_re + r"/s", text, re.I)
    if speed_match:
        try:
            speed = to_bytes((speed_match.group(1), speed_match.group(2)))
        except Exception:
            pass
    eta_match = re.search(r"(?:eta|remaining)\s*[:=]?\s*(\d+):(\d{2})", text, re.I)
    if eta_match:
        eta = int(eta_match.group(1)) * 60 + int(eta_match.group(2))
    return percent, downloaded, total, speed, eta


def _render_deployment_hud(bot_id, start_time=None):
    state = _deployment_state(bot_id)
    now = time.time()
    started = start_time or state.get("started_at") or now
    elapsed = max(0.0, now - started)
    overall_verified = bool(state.get("overall_progress_verified", False))
    percent = float(state.get("percent") or 0) if overall_verified else None
    package_percent = state.get("package_percent")
    total = int(state.get("package_total") or 0)
    idx = int(state.get("package_index") or 0)
    speed = float(state.get("speed_bps") or 0)
    eta = state.get("eta_seconds")
    if eta is None and speed > 0 and state.get("total_bytes") and state.get("downloaded") is not None:
        remaining = max(0, int(state.get("total_bytes", 0)) - int(state.get("downloaded", 0)))
        eta = remaining / speed if remaining else 0
    lines = [
        f"⚙️ **{state.get('stage', 'Deployment')}**",
        "",
        (f"`[{get_progress_bar(percent, 18)}] {percent:.0f}%`"
         if overall_verified else "`[··················]` **Overall: CALCULATING**"),
        "",
        f"⚡ **Status:** `{safe_text(state.get('action', 'Working'), 180)}`",
    ]
    package = state.get("package")
    if package:
        pkg_line = f"📦 **Package:** `{safe_text(package, 100)}`"
        if total:
            pkg_line += f"  `[{idx}/{total}]`"
        lines.append(pkg_line)
        if package_percent is not None:
            lines.append(f"   ↳ `[{get_progress_bar(package_percent, 14)}] {package_percent:.1f}%`")
        if state.get("total_bytes"):
            lines.append(f"   ↳ `{get_readable_size(state.get('downloaded', 0))} / {get_readable_size(state.get('total_bytes', 0))}`")
        if speed > 0:
            lines.append(f"   ↳ Speed: `{get_readable_size(speed)}/s`  •  ETA: `{_format_duration(eta)}`")
    lines.extend([
        "",
        f"📦 Packages: `{idx}/{total}`  •  ✅ `{state.get('installed', 0)}`  •  ❌ `{state.get('failed', 0)}`",
        f"⏱️ Elapsed: `{_format_duration(elapsed)}`  •  Current ETA: `{_format_duration(eta)}`",
        f"🖥️ Server: `{round(psutil.cpu_percent(interval=None), 1) if psutil else 'UNKNOWN'}% CPU`  •  `{get_readable_size(psutil.virtual_memory().used) if psutil else 'UNKNOWN'} RAM`",
        "",
        f"🧾 `{safe_text(state.get('last_event', ''), 220)}`",
    ])
    events = list(state.get("events", []))[-5:]
    if events:
        lines.extend(["", "**Live Events**"])
        lines.extend(f"`{safe_text(e, 180)}`" for e in events)
    return "\n".join(lines)


def _pip_stream_install(bot_id, command, chat_id, msg_id, start_time, package_label=None, overall_percent=60):
    """Run pip with streamed output, bounded timeout, and live HUD updates.

    A dedicated reader thread prevents a quiet subprocess pipe from making
    ``stdout.read()`` block forever and bypassing the configured timeout.
    """
    state = _deployment_state(bot_id)
    _deployment_event(
        bot_id,
        f"Starting pip: {package_label or 'dependency set'}",
        stage="Dependency Engine",
        action=f"Starting `{package_label or 'dependencies'}`",
        percent=overall_percent,
        package=package_label,
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=False,
        bufsize=0,
    )
    output_queue = queue.Queue(maxsize=512)
    sentinel = object()

    def _reader():
        try:
            if process.stdout is None:
                return
            while True:
                chunk = process.stdout.read(256)
                if not chunk:
                    break
                try:
                    output_queue.put(chunk, timeout=1)
                except queue.Full:
                    # Keep the deployment bounded even if the producer is
                    # excessively noisy; retain recent output rather than
                    # allowing unbounded memory growth.
                    try:
                        output_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        output_queue.put_nowait(chunk)
                    except queue.Full:
                        pass
        except Exception as exc:
            try:
                output_queue.put_nowait(("__READER_ERROR__", repr(exc)))
            except queue.Full:
                pass
        finally:
            try:
                output_queue.put_nowait(sentinel)
            except queue.Full:
                pass

    reader = threading.Thread(target=_reader, name=f"pip-reader-{bot_id}", daemon=True)
    reader.start()

    buffer = b""
    last_hud = 0.0
    started = time.time()
    deadline = started + max(1, PIP_INSTALL_TIMEOUT)
    rc = None
    timed_out = False
    try:
        reader_done = False
        while not reader_done:
            remaining = deadline - time.time()
            if remaining <= 0:
                timed_out = True
                try:
                    process.kill()
                except Exception:
                    pass
                break

            try:
                item = output_queue.get(timeout=min(0.5, remaining))
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    reader_done = True
                continue

            if item is sentinel:
                reader_done = True
                continue
            if isinstance(item, tuple) and item and item[0] == "__READER_ERROR__":
                _deployment_event(bot_id, "pip output reader failed", action="Output reader error")
                continue

            buffer += item
            while b"\n" in buffer or b"\r" in buffer:
                positions = [p for p in (buffer.find(b"\n"), buffer.find(b"\r")) if p >= 0]
                pos = min(positions)
                raw, buffer = buffer[:pos], buffer[pos + 1:]
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                pct, down, total_bytes, speed, eta = _parse_progress_line(line)
                updates = {"action": safe_text(line, 180), "percent": overall_percent}
                if pct is not None:
                    updates["package_percent"] = pct
                if down is not None:
                    updates["downloaded"] = down
                if total_bytes is not None:
                    updates["total_bytes"] = total_bytes
                if speed is not None:
                    updates["speed_bps"] = speed
                if eta is not None:
                    updates["eta_seconds"] = eta
                _deployment_event(bot_id, safe_text(line, 220), **updates)
                now = time.time()
                if now - last_hud >= LIVE_HUD_UPDATE_SECONDS:
                    update_hud(
                        chat_id, msg_id, state.get("stage", "Dependency Engine"),
                        state.get("action", "Installing"), state.get("percent", overall_percent),
                        start_time, bot_id=bot_id,
                    )
                    last_hud = now

        if buffer:
            line = buffer.decode("utf-8", "replace").strip()
            if line:
                _deployment_event(bot_id, safe_text(line, 220), action=safe_text(line, 180))

        if timed_out:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except Exception:
                    pass
                try:
                    process.wait(timeout=5)
                except Exception:
                    pass
            raise TimeoutError(f"pip command timed out after {PIP_INSTALL_TIMEOUT}s")

        try:
            rc = process.wait(timeout=max(1, min(10, int(deadline - time.time()) + 1)))
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
            raise TimeoutError(f"pip command timed out after {PIP_INSTALL_TIMEOUT}s")
    finally:
        if process.stdout:
            try:
                process.stdout.close()
            except Exception:
                pass

    duration = max(0.1, time.time() - started)
    if rc != 0:
        tail = list(_deployment_state(bot_id).get("events", []))[-8:]
        raise RuntimeError("pip installation failed: " + " | ".join(tail))
    return duration


def _ensure_bot_venv(bot_id, chat_id=None, msg_id=None, start_time=None):
    bot_dir = os.path.abspath(os.path.join(HOST_DIR, bot_id))
    venv_dir = os.path.join(bot_dir, ".venv")
    python_path = os.path.join(venv_dir, "Scripts" if os.name == "nt" else "bin", "python")
    if os.path.isfile(python_path):
        return python_path
    if not ISOLATED_BOT_ENVS:
        return sys.executable
    _deployment_event(bot_id, "Creating isolated Python environment", stage="Runtime Isolation", action="Creating per-bot virtual environment", percent=48)
    if chat_id and msg_id and start_time:
        update_hud(chat_id, msg_id, "Runtime Isolation", "Creating per-bot virtual environment", 48, start_time, bot_id=bot_id)
    result = subprocess.run([sys.executable, "-m", "venv", venv_dir], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
    if result.returncode != 0 or not os.path.isfile(python_path):
        raise RuntimeError("Unable to create bot virtual environment: " + safe_text(result.stderr[-1200:]))
    return python_path


# ============================================================
# DEPENDENCY INSTALLER
# ============================================================

def auto_install_packages_verified(
    modules,
    chat_id,
    msg_id,
    start_time,
    bot_id=None,
):
    if not modules:
        return True, ""
    modules = list(dict.fromkeys(modules))[:MAX_DEPENDENCY_COUNT]
    total = len(modules)
    bot_id = bot_id or next((bid for bid, st in user_deploy_states.items() if st.get("msg_id") == msg_id), "UNKNOWN")
    state = _deployment_state(bot_id)
    state["package_total"] = total
    state["pending"] = total
    for index, module in enumerate(modules, start=1):
        import_name = module.split()[0].replace("-", "_")
        overall = 50 + int((index - 1) / max(1, total) * 25)
        with deployment_runtime_lock:
            state.update({"package_index": index, "package": module, "package_percent": None, "downloaded": 0, "total_bytes": 0, "speed_bps": 0, "eta_seconds": None, "percent": overall, "pending": total - index + 1})
        try:
            runtime_python = _ensure_bot_venv(bot_id, chat_id, msg_id, start_time)
            probe_command = _docker_probe_command(bot_id, import_name) if SANDBOX_MODE in {"docker", "required"} else [runtime_python, "-c", "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)", import_name]
            probe = subprocess.run(probe_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            if probe.returncode == 0:
                state["installed"] = int(state.get("installed", 0)) + 1
                state["pending"] = max(0, total - index)
                _deployment_event(bot_id, f"Already installed: {module}", action=f"Already installed → `{module}`", percent=overall)
                update_hud(chat_id, msg_id, "Dependency Engine", f"Already installed → `{module}`", overall, start_time, bot_id=bot_id)
                continue
        except Exception:
            pass
        try:
            python_cmd = _ensure_bot_venv(bot_id, chat_id, msg_id, start_time)
            _deployment_event(bot_id, f"Installing {module}", action=f"Installing `{module}`", percent=overall)
            update_hud(chat_id, msg_id, "Dependency Engine", f"Installing `{module}`", overall, start_time, bot_id=bot_id)
            install_command = (_docker_install_command(bot_id, [*module.split(), "--no-cache-dir", "--progress-bar", "on", "--disable-pip-version-check", "--no-input"]) if SANDBOX_MODE in {"docker", "required"} else [python_cmd, "-m", "pip", "install", *module.split(), "--no-cache-dir", "--progress-bar", "on", "--disable-pip-version-check", "--no-input"])
            _pip_stream_install(bot_id, install_command, chat_id, msg_id, start_time, module, overall)
            state["installed"] = int(state.get("installed", 0)) + 1
            state["pending"] = max(0, total - index)
            _deployment_event(bot_id, f"Installed {module}", action=f"Installed `{module}`", percent=overall + int(25 / max(1, total)))
        except Exception as exc:
            state["failed"] = int(state.get("failed", 0)) + 1
            state["last_error"] = safe_text(exc, 1200)
            _deployment_event(bot_id, f"FAILED {module}: {exc}", action=f"Failed `{module}`", percent=overall)
            return False, f"Failed to install `{module}`.\n\n{safe_text(exc, 1800)}"
    return True, ""


# ============================================================
# HUD
# ============================================================

def update_hud(
    chat_id,
    msg_id,
    title,
    action,
    percent,
    start_time,
    bot_id=None,
    verified=False,
):
    if bot_id is None:
        bot_id = next((bid for bid, st in user_deploy_states.items() if st.get("msg_id") == msg_id), None)
    if bot_id:
        state = _deployment_state(bot_id)
        with deployment_runtime_lock:
            if percent is None:
                state.update({"stage": title, "action": action, "percent": None, "overall_progress_verified": False})
            else:
                state.update({"stage": title, "action": action, "percent": max(0, min(100, float(percent))), "overall_progress_verified": bool(verified)})
        text = _render_deployment_hud(bot_id, start_time)
    else:
        elapsed = round(time.time() - start_time, 1)
        if percent is None:
            progress_text = "`[··········]` **Progress: CALCULATING**"
        else:
            progress_text = f"`[{get_progress_bar(percent)}] {float(percent):.0f}%`"
        text = f"⚙️ **{title}**\n\n{progress_text}\n\n⚡ **Status:** `{action}`\n⏱️ **Elapsed:** `{elapsed}s`"
    try:
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="Markdown")
    except Exception:
        pass


# ============================================================
# LONG MESSAGE SENDER
# ============================================================

def send_long_message(
    chat_id,
    text,
    parse_mode=None,
    reply_markup=None,
    is_code=False,
):

    chunk_size = 3900

    if not text:
        text = "No output."

    parts = [
        text[i:i + chunk_size]
        for i in range(
            0,
            len(text),
            chunk_size,
        )
    ]

    for index, part in enumerate(
        parts
    ):

        markup = (
            reply_markup
            if index == len(parts) - 1
            else None
        )

        if is_code:
            msg_text = (
                "```\n"
                + part
                + "\n```"
            )
        else:
            msg_text = part

        try:

            bot.send_message(
                chat_id,
                msg_text,
                parse_mode=parse_mode,
                reply_markup=markup,
            )

        except Exception:
            try:
                bot.send_message(
                    chat_id,
                    part,
                    reply_markup=markup,
                )
            except Exception:
                pass

        if len(parts) > 1:
            time.sleep(0.25)


# ============================================================
# SAFE ZIP EXTRACTION
# ============================================================

def safe_extract_zip(zip_path, destination, max_compressed_bytes=None,
                     max_uncompressed_bytes=None, max_files=None, max_ratio=100.0):
    """Safely extract a ZIP with preflight + streaming quota enforcement."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    max_compressed_bytes = MAX_UPLOAD_BYTES if max_compressed_bytes is None else max_compressed_bytes
    max_uncompressed_bytes = MAX_BOT_DISK_BYTES if max_uncompressed_bytes is None else max_uncompressed_bytes
    max_files = MAX_PROJECT_FILES if max_files is None else max_files
    archive_size = os.path.getsize(zip_path)
    if archive_size > max_compressed_bytes:
        raise ResourceLimitError("Compressed ZIP size limit exceeded before extraction.")
    total = 0
    count = 0
    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        for info in infos:
            name = info.filename.replace("\\", "/")
            parts = [x for x in name.split("/") if x not in ("", ".")]
            if not name or name.startswith("/") or ".." in parts:
                raise SecurityError("Unsafe ZIP path detected.")
            # Reject symlink entries instead of materializing attacker-controlled links.
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and (mode & 0o170000) == 0o120000:
                raise SecurityError("ZIP symlink entries are not allowed.")
            if not name.endswith("/"):
                count += 1
                if count > max_files:
                    raise ResourceLimitError("ZIP file-count limit exceeded.")
                ratio = float(info.file_size) / max(1, int(info.compress_size))
                if info.file_size and ratio > max_ratio:
                    raise SecurityError("ZIP compression-ratio limit exceeded.")
                total += max(0, int(info.file_size))
                if total > max_uncompressed_bytes:
                    raise ResourceLimitError("ZIP extraction quota exceeded.")
        extracted = 0
        for info in infos:
            if info.filename.endswith("/"):
                continue
            target = (destination / info.filename).resolve()
            if target != destination and destination not in target.parents:
                raise SecurityError("ZIP path escaped destination.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    extracted += len(chunk)
                    if extracted > max_uncompressed_bytes:
                        raise ResourceLimitError("Extraction quota exceeded during write.")
                    dst.write(chunk)
    validate_project_limits(destination, max_files=max_files, max_bytes=max_uncompressed_bytes)
    return {"files": count, "uncompressed_bytes": total, "compressed_bytes": archive_size}


# ============================================================
# BOT ID
# ============================================================

def generate_bot_id():

    while True:

        bot_id = (
            "BOT-"
            + str(
                random.randint(
                    1000,
                    9999,
                )
            )
        )

        if (
            bot_id not in hosted_processes
            and bot_id not in user_deploy_states
            and not os.path.exists(
                os.path.join(
                    HOST_DIR,
                    bot_id,
                )
            )
        ):
            return bot_id


# ============================================================
# VERSION BACKUP
# ============================================================

def create_bot_version(
    bot_id,
    reason="update",
):

    bot_dir = os.path.join(
        HOST_DIR,
        bot_id,
    )

    if not os.path.isdir(bot_dir):
        return None

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    version_id = (
        f"v{timestamp}_"
        f"{random.randint(100, 999)}"
    )

    version_root = os.path.join(
        VERSION_DIR,
        bot_id,
        version_id,
    )

    os.makedirs(
        version_root,
        exist_ok=True,
    )

    try:

        shutil.copytree(
            bot_dir,
            version_root,
            dirs_exist_ok=True,
        )

        versions = bot_versions.setdefault(
            bot_id,
            [],
        )

        versions.append(
            {
                "version": version_id,
                "reason": reason,
                "created_at": now_iso(),
                "path": version_root,
            }
        )

        while len(versions) > MAX_VERSIONS_PER_BOT:

            old = versions.pop(
                0
            )

            old_path = old.get(
                "path"
            )

            if old_path:
                shutil.rmtree(
                    old_path,
                    ignore_errors=True,
                )

        save_registry()

        return version_id

    except Exception:

        shutil.rmtree(
            version_root,
            ignore_errors=True,
        )

        raise


# ============================================================
# ROLLBACK
# ============================================================

def rollback_bot(bot_id, version_id, owner_id):
    """Transactional rollback with staged validation and post-start verification."""
    lock = get_bot_lock(bot_id)
    with lock:
        data = hosted_processes.get(bot_id)
        metadata = bot_metadata.get(bot_id, {})
        if not is_admin(owner_id):
            owner = (data or {}).get("owner_id", metadata.get("owner_id", -1))
            if int(owner) != int(owner_id):
                return False, "Permission denied."
        versions = bot_versions.get(bot_id, [])
        selected = next((v for v in versions if v.get("version") == version_id), None)
        if not selected:
            return False, "Version not found."
        source = selected.get("path")
        if not source or not os.path.isdir(source):
            return False, "Version data missing."
        destination = Path(HOST_DIR) / bot_id
        staging = Path(TEMP_DIR) / f"rollback_{bot_id}_{uuid.uuid4().hex}"
        previous = Path(HOST_DIR) / f".{bot_id}.rollback_previous"
        was_running = is_bot_running(bot_id)
        entry_file = (data or {}).get("entry_file") or metadata.get("entry_file", "main.py")
        create_bot_version(bot_id, reason="pre_rollback")
        os.makedirs(staging, exist_ok=True)
        activated = False
        try:
            shutil.copytree(source, staging, dirs_exist_ok=True)
            root = staging.resolve()
            entry_path = (staging / entry_file).resolve()
            if not str(entry_path).startswith(str(root) + os.sep):
                raise ValidationError("Rollback entry path escapes staging directory.")
            if not entry_path.is_file():
                raise ValidationError("Rollback entry file is missing.")
            validate_project_limits(staging, MAX_PROJECT_FILES, MAX_BOT_DISK_BYTES)
            verify_python_tree(staging)
            if was_running:
                stop_script_process(bot_id, reason="rollback_prepare")
            if previous.exists():
                shutil.rmtree(previous, ignore_errors=True)
            if destination.exists():
                os.replace(str(destination), str(previous))
            try:
                os.replace(str(staging), str(destination))
                activated = True
            except Exception:
                if previous.exists() and not destination.exists():
                    os.replace(str(previous), str(destination))
                raise
            if was_running:
                result = start_bot_once(bot_id, entry_file, owner_id, reason="rollback", notify=False)
                if not (result.get("started") or result.get("already_running")):
                    raise DeploymentError("Rollback candidate failed to start.")
                time.sleep(0.5)
                ok, health_message = HealthVerifier.verify_process(get_process(bot_id))
                if not ok:
                    raise DeploymentError(f"Rollback post-start health verification failed: {health_message}")
            if previous.exists():
                shutil.rmtree(previous, ignore_errors=True)
            save_registry()
            security_audit_event("rollback_verified", bot_id, owner_id, version=version_id, was_running=was_running)
            return True, f"Rollback to `{version_id}` completed and verified."
        except Exception as exc:
            try:
                if activated and destination.exists() and previous.exists():
                    if is_bot_running(bot_id):
                        stop_script_process(bot_id, reason="rollback_recovery")
                    shutil.rmtree(destination, ignore_errors=True)
                    os.replace(str(previous), str(destination))
                if was_running:
                    try:
                        start_bot_once(bot_id, entry_file, owner_id, reason="rollback_recovery", notify=False)
                    except Exception:
                        pass
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            record_error(bot_id, exc)
            security_audit_event("rollback_failed", bot_id, owner_id, version=version_id, error=type(exc).__name__)
            return False, f"Rollback failed safely: {safe_text(exc, 1200)}"


# ============================================================
# HEALTH MONITOR
# ============================================================

def _process_tree_metrics(pid):
    if not psutil:
        return {"memory": None, "cpu": None, "processes": None, "threads": None, "open_files": None, "connections": None}
    try:
        root = psutil.Process(pid)
        procs = [root] + root.children(recursive=True)
        memory = 0
        cpu = 0.0
        threads = 0
        open_files = 0
        connections = 0
        alive = 0
        for proc in procs:
            try:
                if not proc.is_running():
                    continue
                alive += 1
                memory += proc.memory_info().rss
                cpu += float(proc.cpu_percent(interval=0.0))
                threads += int(proc.num_threads())
                try: open_files += len(proc.open_files())
                except Exception: pass
                try: connections += len(proc.net_connections(kind="inet"))
                except Exception: pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"memory": memory, "cpu": cpu, "processes": alive, "threads": threads, "open_files": open_files, "connections": connections}
    except Exception:
        return {"memory": None, "cpu": None, "processes": None, "threads": None, "open_files": None, "connections": None}

def inspect_bot_health(bot_id):
    data = hosted_processes.get(bot_id)
    if not data:
        return {"status": "NOT_FOUND", "memory": None, "cpu": None, "pid": None, "processes": None, "threads": None, "open_files": None, "connections": None}
    process = data.get("process")
    if process is None:
        return {"status": "STOPPED", "memory": None, "cpu": None, "pid": None, "processes": None, "threads": None, "open_files": None, "connections": None}
    if process.poll() is not None:
        return {"status": "STOPPED", "memory": None, "cpu": None, "pid": process.pid, "processes": 0, "threads": 0, "open_files": 0, "connections": 0}
    m = _process_tree_metrics(process.pid)
    if psutil and m.get("memory") is not None:
        metrics = ensure_metrics(bot_id)
        metrics["peak_memory"] = max(int(metrics.get("peak_memory", 0)), int(m["memory"]))
    ensure_metrics(bot_id)["last_health_check"] = now_iso()
    return {"status": "RUNNING", "pid": process.pid, **m}


# ============================================================
# AUTO HEALING
# ============================================================

def can_auto_restart(
    bot_id,
):

    history = restart_history.setdefault(
        bot_id,
        collections.deque(),
    )

    current = time.time()

    while history and (
        current - history[0]
        > AUTO_RESTART_WINDOW
    ):
        history.popleft()

    return len(history) < AUTO_RESTART_LIMIT


def register_auto_restart(
    bot_id,
):

    history = restart_history.setdefault(
        bot_id,
        collections.deque(),
    )

    history.append(
        time.time()
    )


def bot_disk_usage_bytes(bot_id):
    root = Path(HOST_DIR, bot_id)
    total = 0
    if not root.exists():
        return 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {"__pycache__"}]
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                continue
    return total

def auto_healing_monitor():

    while not SHUTDOWN_REQUESTED:

        time.sleep(8)

        for bot_id, data in list(
            hosted_processes.items()
        ):

            try:

                rotate_log_if_needed(
                    bot_id
                )

                process = data.get(
                    "process"
                )

                if process is None:
                    continue

                if process.poll() is None:

                    health = inspect_bot_health(
                        bot_id
                    )

                    # Multi-signal resource guard: process tree, memory, CPU, disk, threads, and connections.
                    cpu_value = health.get("cpu")
                    if cpu_value is not None and cpu_value > MAX_BOT_CPU_PERCENT:
                        RESOURCE_GUARD_STRIKES[bot_id] += 1
                    else:
                        RESOURCE_GUARD_STRIKES[bot_id] = max(0, RESOURCE_GUARD_STRIKES[bot_id] - 1)

                    if RESOURCE_GUARD_STRIKES[bot_id] >= CPU_LIMIT_STRIKES:
                        owner_id = data.get("owner_id")
                        security_audit_event("cpu_limit_enforced", bot_id, owner_id, cpu=health.get("cpu", 0), limit=MAX_BOT_CPU_PERCENT)
                        stop_script_process(bot_id, reason="cpu_limit")
                        try:
                            bot.send_message(owner_id, f"🚨 **Health Guard**\n\n🤖 `{bot_id}`\n🧠 CPU limit sustained above `{MAX_BOT_CPU_PERCENT:.0f}%`.\n🛑 Bot stopped safely.", parse_mode="Markdown")
                        except Exception:
                            pass
                        continue

                    if health.get("processes") is not None and health["processes"] > MAX_BOT_PROCESSES:
                        owner_id = data.get("owner_id")
                        security_audit_event("process_limit_enforced", bot_id, owner_id, processes=health["processes"], limit=MAX_BOT_PROCESSES)
                        stop_script_process(bot_id, reason="process_limit")
                        continue
                    if health.get("threads") is not None and health["threads"] > MAX_BOT_THREADS:
                        owner_id = data.get("owner_id")
                        security_audit_event("thread_limit_enforced", bot_id, owner_id, threads=health["threads"], limit=MAX_BOT_THREADS)
                        stop_script_process(bot_id, reason="thread_limit")
                        continue
                    if health.get("connections") is not None and health["connections"] > MAX_BOT_CONNECTIONS:
                        owner_id = data.get("owner_id")
                        security_audit_event("connection_limit_enforced", bot_id, owner_id, connections=health["connections"], limit=MAX_BOT_CONNECTIONS)
                        stop_script_process(bot_id, reason="connection_limit")
                        continue
                    disk_used = bot_disk_usage_bytes(bot_id)
                    if disk_used > MAX_BOT_DISK_BYTES:
                        owner_id = data.get("owner_id")
                        security_audit_event("disk_limit_enforced", bot_id, owner_id, bytes=disk_used, limit=MAX_BOT_DISK_BYTES)
                        stop_script_process(bot_id, reason="disk_limit")
                        continue

                    if health.get("memory") is not None and health["memory"] > MAX_BOT_RAM_BYTES:

                        owner_id = data.get(
                            "owner_id"
                        )

                        security_audit_event("memory_limit_enforced", bot_id, owner_id, memory=health.get("memory", 0), limit=MAX_BOT_RAM_BYTES)
                        stop_script_process(
                            bot_id,
                            reason="memory_limit",
                        )

                        try:
                            bot.send_message(
                                owner_id,
                                (
                                    f"🚨 **Health Guard**\n\n"
                                    f"🤖 `{bot_id}`\n"
                                    f"💾 Memory limit exceeded.\n"
                                    f"🛑 Bot stopped safely."
                                ),
                                parse_mode="Markdown",
                            )
                        except Exception:
                            pass

                    continue

                if data.get(
                    "manual_stop",
                    False,
                ):
                    continue

                owner_id = data.get(
                    "owner_id"
                )

                log_path = data.get(
                    "log_file"
                )

                missing_package = None

                if log_path and os.path.exists(
                    log_path
                ):

                    try:

                        with open(
                            log_path,
                            "r",
                            encoding="utf-8",
                            errors="ignore",
                        ) as handle:

                            tail = handle.read()[
                                -6000:
                            ]

                        match = re.search(
                            r"No module named ['\"]([^'\"]+)",
                            tail,
                        )

                        if match:
                            missing_package = (
                                match.group(1)
                            )

                    except Exception:
                        pass

                metric_increment(
                    bot_id,
                    "crashes",
                )

                if not can_auto_restart(
                    bot_id
                ):
                    continue

                register_auto_restart(
                    bot_id
                )

                if missing_package:

                    target_package = PIP_MAP.get(
                        missing_package,
                        missing_package,
                    )

                    try:

                        runtime_python = data.get("runtime_python") or sys.executable
                        subprocess.run(
                            [
                                runtime_python,
                                "-m",
                                "pip",
                                "install",
                                target_package,
                                "--disable-pip-version-check",
                                "--no-input",
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=300,
                        )

                    except Exception as exc:

                        record_error(
                            bot_id,
                            exc,
                        )

                entry_file = data.get(
                    "entry_file"
                )

                try:

                    result = start_bot_once(
                        bot_id,
                        entry_file,
                        owner_id,
                        reason="auto_recovery",
                        notify=False,
                        verify_startup=True,
                    )

                    if result["started"]:

                        try:
                            bot.send_message(
                                owner_id,
                                (
                                    f"🩺 **Auto Recovery**\n\n"
                                    f"🤖 `{bot_id}`\n"
                                    f"♻️ Process recovered.\n"
                                    f"🆔 PID: `{result['pid']}`"
                                ),
                                parse_mode="Markdown",
                            )
                        except Exception:
                            pass

                except Exception as exc:

                    record_error(
                        bot_id,
                        exc,
                    )

            except Exception as exc:

                logger.exception(
                    "Watchdog error for %s",
                    bot_id,
                )

                record_error(
                    bot_id,
                    exc,
                )

        status_cache.cleanup()


# ============================================================
# DEPLOYMENT WORKER QUEUE
# ============================================================

def enqueue_deployment(task):
    """Bounded, idempotent deployment enqueue with explicit backpressure."""
    bot_id = str(task.get("bot_id") or "")
    if not bot_id:
        raise ValidationError("Deployment task is missing bot_id.")
    key = f"{bot_id}:{task.get('install_type','auto')}"
    with deployment_queue_lock:
        if key in deployment_queue_keys:
            return False, "Deployment already queued or running."
        try:
            deployment_queue.put_nowait(task)
        except queue.Full:
            return False, "Deployment queue is full. Try again when capacity is available."
        deployment_queue_keys.add(key)
    return True, "Queued"

def _release_deployment_key(task):
    bot_id = str(task.get("bot_id") or "")
    key = f"{bot_id}:{task.get('install_type','auto')}"
    with deployment_queue_lock:
        deployment_queue_keys.discard(key)

def deployment_worker():

    while not SHUTDOWN_REQUESTED:

        try:

            task = deployment_queue.get(
                timeout=1
            )

        except queue.Empty:
            continue

        try:

            finalize_deployment(
                task["chat_id"],
                task["msg_id"],
                task["bot_id"],
                task["install_type"],
                task.get(
                    "manual_req_path"
                ),
                task.get("skip_dependencies", False),
            )

        except Exception as exc:

            logger.exception(
                "Deployment worker failed."
            )

            try:
                bot.send_message(
                    task["chat_id"],
                    (
                        "❌ Deployment worker error:\n"
                        f"`{safe_text(exc, 1000)}`"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        finally:
            deployment_queue.task_done()
            _release_deployment_key(task)


def start_deployment_workers():

    for index in range(
        max(1, DEPLOYMENT_WORKERS)
    ):

        thread = threading.Thread(
            target=deployment_worker,
            name=f"deploy-worker-{index + 1}",
            daemon=True,
        )

        thread.start()

        deployment_workers.append(
            thread
        )


# ============================================================
# MTProto DOWNLOAD
# ============================================================

def mtproto_download(
    chat_id,
    message_id,
    dest_path,
):

    if not MTPROTO_AVAILABLE:
        raise RuntimeError(
            "Pyrogram is not installed."
        )

    if not GLOBAL_API_ID or not GLOBAL_API_HASH:
        raise RuntimeError(
            "MTProto credentials are not configured."
        )

    async def run():

        async with Client(
            "mtproto_engine",
            api_id=GLOBAL_API_ID,
            api_hash=GLOBAL_API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True,
        ) as client:

            message = await client.get_messages(
                chat_id,
                message_id,
            )

            await client.download_media(
                message,
                file_name=dest_path,
            )

    loop = asyncio.new_event_loop()

    try:

        asyncio.set_event_loop(
            loop
        )

        loop.run_until_complete(
            run()
        )

    finally:

        loop.close()


# ============================================================
# MTProto UPLOAD
# ============================================================

def mtproto_upload(
    chat_id,
    file_path,
    caption,
):

    if not MTPROTO_AVAILABLE:
        raise RuntimeError(
            "Pyrogram is not installed."
        )

    if not GLOBAL_API_ID or not GLOBAL_API_HASH:
        raise RuntimeError(
            "MTProto credentials are not configured."
        )

    async def run():

        async with Client(
            "mtproto_engine",
            api_id=GLOBAL_API_ID,
            api_hash=GLOBAL_API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True,
        ) as client:

            await client.send_document(
                chat_id,
                document=file_path,
                caption=caption,
            )

    loop = asyncio.new_event_loop()

    try:

        asyncio.set_event_loop(
            loop
        )

        loop.run_until_complete(
            run()
        )

    finally:

        loop.close()


# ============================================================
# SMART ENV / TOKEN MANAGER
# ============================================================

ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_REF_RE = re.compile(r"(?:os\.environ(?:\.get)?\s*\[\s*['\"]([^'\"]+)['\"]\s*\]|os\.getenv\s*\(\s*['\"]([^'\"]+)['\"])")
PLACEHOLDER_RE = re.compile(r"(?i)^(?:your[_ -]?|enter[_ -]?|replace[_ -]?|put[_ -]?|paste[_ -]?|change[_ -]?|add[_ -]?|example[_ -]?|dummy[_ -]?|test[_ -]?|xxx|<.*?>|\$\{.*\}|\[.*\])")
SENSITIVE_NAME_RE = re.compile(r"(?i)(?:token|api[_-]?key|secret|password|passwd|credential|auth|database[_-]?url|private[_-]?key)")

env_collection_states: Dict[str, Dict[str, Any]] = {}


def _bot_env_store(bot_id):
    return bot_envs.setdefault(str(bot_id), {})

def _validate_env_payload(values):
    total = 0
    for key, value in values.items():
        if not ENV_NAME_RE.match(str(key)):
            raise ValueError(f"Invalid environment variable name: {key}")
        if len(str(key)) > 256:
            raise ValueError("Environment variable name is too long.")
        if "\x00" in str(value):
            raise ValueError("NUL byte is not allowed in environment values.")
        total += len(str(key).encode()) + len(str(value).encode())
    if total > MAX_ENV_BYTES:
        raise ResourceLimitError("Environment payload exceeds configured limit.")
    return True

def save_bot_env_values(bot_id, values):
    _validate_env_payload(values)
    store = _bot_env_store(bot_id)
    for key, value in values.items():
        store[str(key)] = str(value)
    save_registry()
    return list(values)

def _env_store_for(user_id):
    return user_custom_envs.setdefault(str(user_id), {})


def _mask_secret(value):
    if not value:
        return "(empty)"
    if len(value) <= 6:
        return "••••••"
    return value[:2] + "••••••" + value[-2:]


def parse_env_text(text):
    """Parse KEY=VALUE / KEY:VALUE / export KEY=VALUE safely."""
    result = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if ENV_NAME_RE.match(key):
            result[key] = value
    return result


def save_env_values(user_id, values):
    store = _env_store_for(user_id)
    changed = []
    for key, value in values.items():
        if ENV_NAME_RE.match(key):
            store[key] = value
            changed.append(key)
    save_registry()
    return changed


def detect_project_env_requirements(bot_dir):
    """Find explicit ENV references and obvious empty/placeholder credential variables."""
    found = []
    seen = set()
    for root, _, files in os.walk(bot_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                text = Path(path).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for match in ENV_REF_RE.finditer(text):
                key = match.group(1) or match.group(2)
                if key and key not in seen:
                    seen.add(key); found.append(key)
            try:
                tree = ast.parse(text)
            except Exception:
                tree = None
            if tree:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                            continue
                        key = node.targets[0].id
                        if not SENSITIVE_NAME_RE.search(key):
                            continue
                        value = node.value
                        is_empty = isinstance(value, ast.Constant) and isinstance(value.value, str) and not value.value.strip()
                        is_placeholder = isinstance(value, ast.Constant) and isinstance(value.value, str) and PLACEHOLDER_RE.search(value.value.strip())
                        if is_empty or is_placeholder:
                            if key not in seen:
                                seen.add(key); found.append(key)
    return found


def env_menu_markup():
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(
        InlineKeyboardButton("➕ Add / Paste", callback_data="env_add"),
        InlineKeyboardButton("📋 Variables", callback_data="env_list"),
        InlineKeyboardButton("🔎 Search", callback_data="env_search"),
        InlineKeyboardButton("✏️ Update", callback_data="env_update"),
        InlineKeyboardButton("🗑 Delete", callback_data="env_delete"),
        InlineKeyboardButton("📥 Import .env", callback_data="env_import"),
        InlineKeyboardButton("🧪 Config Check", callback_data="env_check"),
        InlineKeyboardButton("🤖 Bot ENV", callback_data="env_bot_pick"),
        InlineKeyboardButton("📤 Export", callback_data="env_export"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu"),
    )
    return mk


def show_env_manager(chat_id, user_id):
    store = _env_store_for(user_id)
    count = len(store)
    text = (
        "🔐 **ENV / TOKEN MANAGE**\n\n"
        f"Saved variables: `{count}`\n\n"
        "Values are masked. You can paste multiple `KEY=VALUE` lines, "
        "or enter one variable manually."
    )
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=env_menu_markup())


def env_add_input(message):
    if message.text and message.text.lower().strip() == "cancel":
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=env_menu_markup()); return
    raw = message.text or ""
    if message.document:
        try:
            info = bot.get_file(message.document.file_id)
            raw = bot.download_file(info.file_path).decode("utf-8", errors="ignore")
        except Exception as exc:
            bot.send_message(message.chat.id, f"❌ ENV file read failed: `{safe_text(exc, 500)}`", parse_mode="Markdown", reply_markup=env_menu_markup()); return
    values = parse_env_text(raw)
    if not values:
        bot.send_message(message.chat.id, "❌ No valid variables found. Use `KEY=VALUE` lines.", parse_mode="Markdown", reply_markup=env_menu_markup()); return
    keys = save_env_values(message.from_user.id, values)
    bot.send_message(message.chat.id, "✅ Saved: " + ", ".join(f"`{k}`" for k in keys), parse_mode="Markdown", reply_markup=env_menu_markup())


def env_list(chat_id, user_id, prefix=None):
    store = _env_store_for(user_id)
    keys = [k for k in store if not prefix or prefix.lower() in k.lower()]
    if not keys:
        text = "📋 **ENV VARIABLES**\n\nNo matching variables."
    else:
        text = "📋 **ENV VARIABLES**\n\n" + "\n".join(f"🟢 `{k}` → `{_mask_secret(store[k])}`" for k in keys)
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=env_menu_markup())


def env_name_input(message, action):
    key = (message.text or "").strip()
    if key.lower() == "cancel":
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=env_menu_markup()); return
    if not ENV_NAME_RE.match(key):
        bot.send_message(message.chat.id, "❌ Invalid variable name.", reply_markup=env_menu_markup()); return
    store = _env_store_for(message.from_user.id)
    if action == "delete":
        if key in store:
            del store[key]; save_registry(); bot.send_message(message.chat.id, f"🗑 `{key}` deleted.", parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "❌ Variable not found.")
    else:
        bot.send_message(message.chat.id, f"🔐 Send new value for `{key}` or `cancel`.", parse_mode="Markdown")
        bot.register_next_step_handler(message, lambda m, k=key: env_value_input(m, k))
        return
    show_env_manager(message.chat.id, message.from_user.id)


def env_value_input(message, key):
    if not message.text or message.text.lower().strip() == "cancel":
        bot.send_message(message.chat.id, "❌ Cancelled.", reply_markup=env_menu_markup()); return
    save_env_values(message.from_user.id, {key: message.text.strip()})
    bot.send_message(message.chat.id, f"✅ `{key}` updated and masked.", parse_mode="Markdown", reply_markup=env_menu_markup())


def env_search_input(message):
    q = (message.text or "").strip()
    if q.lower() == "cancel":
        show_env_manager(message.chat.id, message.from_user.id); return
    env_list(message.chat.id, message.from_user.id, q)


def env_export(chat_id, user_id):
    store = _env_store_for(user_id)
    if not store:
        bot.send_message(chat_id, "📤 No variables to export.", reply_markup=env_menu_markup()); return
    text = "\n".join(f"{k}=********" for k in store)
    bot.send_message(chat_id, "📤 **Masked ENV Export**\n\n```\n" + text + "\n```", parse_mode="Markdown", reply_markup=env_menu_markup())


def env_start_check(chat_id, user_id):
    store = _env_store_for(user_id)
    if not store:
        bot.send_message(chat_id, "🧪 No saved ENV variables.", reply_markup=env_menu_markup()); return
    text = "🧪 **CONFIGURATION CHECK**\n\n" + "\n".join(f"✅ `{k}`" for k in store)
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=env_menu_markup())


# ============================================================
# SYSTEM REQUIREMENT DOWNLOADER / HOST DEPENDENCY MANAGER
# ============================================================

SYSTEM_REQUIREMENT_MAX_LINES = int(os.environ.get("SYSTEM_REQUIREMENT_MAX_LINES", "500"))
SYSTEM_REQUIREMENT_MAX_TEXT_BYTES = int(os.environ.get("SYSTEM_REQUIREMENT_MAX_TEXT_BYTES", str(512 * 1024)))
SYSTEM_REQUIREMENT_PIP_TIMEOUT = int(os.environ.get("SYSTEM_REQUIREMENT_PIP_TIMEOUT", str(3600)))
SYSTEM_REQUIREMENT_MAX_OUTPUT = int(os.environ.get("SYSTEM_REQUIREMENT_MAX_OUTPUT", "6000"))


def _system_installed_packages():
    """Return the actual packages visible to this engine's Python interpreter."""
    if importlib_metadata is None:
        return {}
    packages = {}
    try:
        for dist in importlib_metadata.distributions():
            name = dist.metadata.get("Name") or dist.name
            if not name:
                continue
            packages[canonicalize_package_name(name)] = {
                "name": str(name),
                "version": str(dist.version or "UNKNOWN"),
            }
    except Exception as exc:
        logger.exception("System package inventory failed.")
        return {"__ERROR__": {"name": "__ERROR__", "version": type(exc).__name__}}
    return packages


def _parse_system_requirements(text):
    """Parse pasted/uploaded requirements without allowing pip global options."""
    if not isinstance(text, str):
        raise ValidationError("Requirements input must be text.")
    if len(text.encode("utf-8", "replace")) > SYSTEM_REQUIREMENT_MAX_TEXT_BYTES:
        raise ResourceLimitError("Requirements input is too large.")
    lines = []
    invalid = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r", "--requirement", "-c", "--constraint", "--index-url", "--extra-index-url", "--trusted-host", "--find-links", "--no-index", "--config-settings", "--target", "--prefix", "--root", "--user")):
            invalid.append((line, "pip option/directive is not accepted by System Requirement Downloader"))
            continue
        # Strip only trailing inline comments when separated by whitespace.
        line = re.sub(r"\s+#.*$", "", line).strip()
        if not line:
            continue
        if PACKAGING_AVAILABLE:
            try:
                req = PackagingRequirement(line)
                if req.marker is not None and not req.marker.evaluate():
                    continue
                key = canonicalize_package_name(req.name)
            except Exception as exc:
                invalid.append((line, f"invalid requirement: {type(exc).__name__}"))
                continue
        else:
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\s*(?:==|~=|>=|<=|!=|>|<).*)?$", line)
            if not match:
                invalid.append((line, "requirements parser unavailable or unsupported syntax"))
                continue
            key = canonicalize_package_name(match.group(1))
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= SYSTEM_REQUIREMENT_MAX_LINES:
            break
    return lines, invalid


def _requirement_satisfied(requirement_line, installed):
    if not PACKAGING_AVAILABLE:
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", requirement_line)
        if not m:
            return False
        return canonicalize_package_name(m.group(1)) in installed
    try:
        req = PackagingRequirement(requirement_line)
        if req.marker is not None and not req.marker.evaluate():
            return True
        current = installed.get(canonicalize_package_name(req.name))
        if not current:
            return False
        if not req.specifier:
            return True
        return req.specifier.contains(current["version"], prereleases=True)
    except Exception:
        return False


def _system_requirements_diff(requirements):
    installed = _system_installed_packages()
    missing = [line for line in requirements if not _requirement_satisfied(line, installed)]
    already = [line for line in requirements if _requirement_satisfied(line, installed)]
    return installed, already, missing


def _record_system_requirement(requirement, status, version=None, error=None):
    key = canonicalize_package_name(re.sub(r"\s*(?:==|~=|>=|<=|!=|>|<).*$", "", requirement).strip())
    with system_requirements_lock:
        system_requirements_catalog[key] = {
            "requirement": requirement,
            "status": status,
            "version": version,
            "error": error,
            "updated_at": now_iso(),
        }


def _chunk_text(text, limit=3800):
    text = str(text)
    return [text[i:i + limit] for i in range(0, len(text), limit)] or [""]


def _system_requirements_summary():
    installed = _system_installed_packages()
    if "__ERROR__" in installed:
        return "❌ Installed-package inventory failed."
    rows = sorted(installed.values(), key=lambda x: x["name"].lower())
    lines = [f"📦 **Installed Python Packages**", f"Total: `{len(rows)}`", ""]
    for item in rows:
        lines.append(f"• `{item['name']}=={item['version']}`")
    return "\n".join(lines)


def system_requirements_menu_markup():
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(
        InlineKeyboardButton("📦 Installed Packages", callback_data="sysreq_list"),
        InlineKeyboardButton("➕ Add / Install", callback_data="sysreq_add"),
        InlineKeyboardButton("🔄 Refresh", callback_data="sysreq_refresh"),
        InlineKeyboardButton("📋 Managed List", callback_data="sysreq_managed"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu"),
    )
    return mk


def show_system_requirements(chat_id, user_id, prefix=None):
    if not is_admin(user_id):
        bot.send_message(chat_id, "❌ System Requirement Downloader is restricted to the master admin because it changes the host Python environment.")
        return
    installed = _system_installed_packages()
    count = max(0, len(installed) - (1 if "__ERROR__" in installed else 0))
    managed = len(system_requirements_catalog)
    text = (
        "⚙️ **SYSTEM REQUIREMENT DOWNLOADER**\n\n"
        f"🐍 Python: `{sys.version.split()[0]}`\n"
        f"📦 Installed packages: `{count}`\n"
        f"🧾 Managed requirements: `{managed}`\n\n"
        "Paste a requirements.txt body or package requirements.\n"
        "Already-satisfied requirements are skipped automatically.\n"
        "Version constraints are respected.\n"
        "Installation runs in the background and is verified after pip completes."
    )
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=system_requirements_menu_markup())


def _send_system_installed_list(chat_id):
    text = _system_requirements_summary()
    for chunk in _chunk_text(text):
        bot.send_message(chat_id, chunk, parse_mode="Markdown")
    bot.send_message(chat_id, "Use the buttons below for another action.", reply_markup=system_requirements_menu_markup())


def _send_system_managed_list(chat_id):
    with system_requirements_lock:
        items = list(system_requirements_catalog.values())
    items.sort(key=lambda x: str(x.get("requirement", "")).lower())
    if not items:
        bot.send_message(chat_id, "📋 **Managed List**\n\nNo requirements have been submitted yet.", parse_mode="Markdown", reply_markup=system_requirements_menu_markup())
        return
    lines = ["📋 **Managed System Requirements**", ""]
    for item in items:
        status = item.get("status", "UNKNOWN")
        version = item.get("version") or "-"
        lines.append(f"• `{safe_text(item.get('requirement',''), 160)}` → `{status}` (`{version}`)")
        if item.get("error"):
            lines.append(f"  ↳ `{safe_text(item['error'], 180)}`")
    for chunk in _chunk_text("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="Markdown")
    bot.send_message(chat_id, "", reply_markup=system_requirements_menu_markup())


def _run_system_requirement_install(message, text):
    chat_id = message.chat.id
    try:
        requirements, invalid = _parse_system_requirements(text)
    except Exception as exc:
        bot.send_message(chat_id, f"❌ Input rejected: `{safe_text(exc, 500)}`", parse_mode="Markdown", reply_markup=system_requirements_menu_markup())
        return
    if not requirements:
        details = "\n".join(f"• `{safe_text(line, 180)}` — {reason}" for line, reason in invalid[:20]) or "No valid requirements found."
        bot.send_message(chat_id, "❌ **No installable requirements**\n\n" + details, parse_mode="Markdown", reply_markup=system_requirements_menu_markup())
        return

    installed, already, missing = _system_requirements_diff(requirements)
    status = bot.send_message(
        chat_id,
        "⏳ **System Requirement Check**\n\n"
        f"📦 Submitted: `{len(requirements)}`\n"
        f"⏭ Already installed/satisfied: `{len(already)}`\n"
        f"📥 To install/upgrade: `{len(missing)}`\n"
        f"⚠️ Invalid/skipped: `{len(invalid)}`",
        parse_mode="Markdown",
        reply_markup=system_requirements_menu_markup(),
    )

    if not missing:
        for req in already:
            current = installed.get(canonicalize_package_name(PackagingRequirement(req).name if PACKAGING_AVAILABLE else re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", req).group(1)))
            _record_system_requirement(req, "INSTALLED", current.get("version") if current else None)
        save_registry()
        bot.send_message(chat_id, "✅ All submitted requirements are already satisfied. Nothing was downloaded.", reply_markup=system_requirements_menu_markup())
        return

    def worker():
        start = time.time()
        req_file = None
        try:
            fd, req_file = tempfile.mkstemp(prefix="system_requirements_", suffix=".txt", dir=TEMP_DIR, text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(missing) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            cmd = [sys.executable, "-m", "pip", "install", "-r", req_file, "--disable-pip-version-check", "--no-input", "--progress-bar", "off"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1)
            output = []
            deadline = time.time() + SYSTEM_REQUIREMENT_PIP_TIMEOUT
            while True:
                if time.time() > deadline:
                    try: proc.kill()
                    except Exception: pass
                    raise TimeoutError(f"pip timed out after {SYSTEM_REQUIREMENT_PIP_TIMEOUT}s")
                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    line = redact_sensitive_text(line.strip(), 500)
                    if line:
                        output.append(line)
                        output = output[-40:]
                elif proc.poll() is not None:
                    break
                else:
                    time.sleep(0.05)
            rc = proc.wait(timeout=10)
            if rc != 0:
                raise RuntimeError("pip failed: " + " | ".join(output[-8:]))
            after = _system_installed_packages()
            still_missing = [req for req in missing if not _requirement_satisfied(req, after)]
            if still_missing:
                raise RuntimeError("Installation command completed but verification failed for: " + ", ".join(still_missing[:12]))
            for req in missing:
                current = after.get(canonicalize_package_name(PackagingRequirement(req).name if PACKAGING_AVAILABLE else re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", req).group(1)))
                _record_system_requirement(req, "INSTALLED", current.get("version") if current else None)
            for req in already:
                current = after.get(canonicalize_package_name(PackagingRequirement(req).name if PACKAGING_AVAILABLE else re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)", req).group(1)))
                _record_system_requirement(req, "SKIPPED", current.get("version") if current else None)
            save_registry()
            elapsed = _format_duration(time.time() - start)
            bot.edit_message_text(
                "✅ **SYSTEM REQUIREMENTS COMPLETE**\n\n"
                f"📦 Submitted: `{len(requirements)}`\n"
                f"⏭ Skipped: `{len(already)}`\n"
                f"📥 Installed/updated: `{len(missing)}`\n"
                f"⚠️ Invalid: `{len(invalid)}`\n"
                f"⏱️ Elapsed: `{elapsed}`\n\n"
                "🔎 Post-install verification: `PASSED`",
                chat_id, status.message_id, parse_mode="Markdown", reply_markup=system_requirements_menu_markup()
            )
        except Exception as exc:
            err = redact_sensitive_text(exc, 1200)
            for req in missing:
                _record_system_requirement(req, "FAILED", error=err)
            try: save_registry()
            except Exception: logger.exception("Failed saving system requirement failure state")
            bot.edit_message_text(
                "❌ **SYSTEM REQUIREMENT INSTALL FAILED**\n\n"
                f"Error: `{safe_text(err, 1000)}`\n\n"
                "No success is reported unless post-install verification passes.",
                chat_id, status.message_id, parse_mode="Markdown", reply_markup=system_requirements_menu_markup()
            )
        finally:
            if req_file:
                try: os.remove(req_file)
                except OSError: pass

    threading.Thread(target=worker, name="system-requirement-installer", daemon=True).start()


def system_requirements_input(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "❌ Access denied.")
        return
    if message.text and message.text.strip().lower() == "cancel":
        show_system_requirements(message.chat.id, message.from_user.id)
        return
    if message.document:
        if (message.document.file_size or 0) > SYSTEM_REQUIREMENT_MAX_TEXT_BYTES:
            bot.send_message(message.chat.id, "❌ requirements file is too large.", reply_markup=system_requirements_menu_markup())
            return
        temp = None
        try:
            info = bot.get_file(message.document.file_id)
            content = bot.download_file(info.file_path)
            text = content.decode("utf-8", "replace")
        except Exception as exc:
            bot.send_message(message.chat.id, f"❌ Could not read requirements file: `{safe_text(exc, 500)}`", parse_mode="Markdown", reply_markup=system_requirements_menu_markup())
            return
        _run_system_requirement_install(message, text)
        return
    _run_system_requirement_install(message, message.text or "")

# ============================================================
# BOT MENUS
# ============================================================

def get_user_menu(
    user_id
):

    markup = InlineKeyboardMarkup(
        row_width=2
    )

    active_bots = [
        bot_id
        for bot_id, data
        in hosted_processes.items()
        if (
            is_admin(user_id)
            or int(
                data.get(
                    "owner_id",
                    -1,
                )
            )
            == int(user_id)
        )
        and is_bot_running(
            bot_id
        )
    ]

    markup.add(

        InlineKeyboardButton(
            "🚀 Deploy New Bot",
            callback_data="host_file",
        ),

        InlineKeyboardButton(
            "🤖 My Bots",
            callback_data="my_bots",
        ),

        InlineKeyboardButton(
            f"🟢 Running ({len(active_bots)})",
            callback_data="my_bots",
        ),

        InlineKeyboardButton(
            "🔍 ID Search Hub",
            callback_data="search_hub",
        ),

        InlineKeyboardButton(
            "🔑 ENV / Token Manager",
            callback_data="manage_env",
        ),

        InlineKeyboardButton(
            "📊 Server Health",
            callback_data="server_ping",
        ),

        InlineKeyboardButton(
            "⚙️ System Requirement Downloader",
            callback_data="system_requirements",
        ),

        InlineKeyboardButton(
            "📦 Storage & Backup",
            callback_data="browse_files",
        ),

        InlineKeyboardButton(
            "🛑 Stop My Bots",
            callback_data="stop_my_bots",
        ),
    )

    if is_admin(user_id):

        markup.add(
            InlineKeyboardButton(
                "👑 Master Admin Panel",
                callback_data="admin_panel",
            )
        )

    return markup


def get_search_hub_menu():

    markup = InlineKeyboardMarkup(
        row_width=1
    )

    markup.add(
        InlineKeyboardButton(
            "🔍 Find Bot by ID",
            callback_data="search_by_id",
        ),
        InlineKeyboardButton(
            "➕ Deploy New Bot",
            callback_data="host_file",
        ),
        InlineKeyboardButton(
            "🔙 Dashboard",
            callback_data="main_menu",
        ),
    )

    return markup


def get_package_menu(
    bot_id
):

    markup = InlineKeyboardMarkup(
        row_width=2
    )

    markup.add(
        InlineKeyboardButton(
            "🧠 Smart Auto-Install",
            callback_data=f"pkg_auto:{bot_id}",
        ),
        InlineKeyboardButton(
            "📝 Manual Requirements",
            callback_data=f"pkg_manual:{bot_id}",
        ),
        InlineKeyboardButton(
            "❌ Cancel",
            callback_data="main_menu",
        ),
    )

    return markup


def get_admin_menu():

    status = (
        "🟢 ON"
        if MAINTENANCE_MODE
        else "🔴 OFF"
    )

    markup = InlineKeyboardMarkup(
        row_width=2
    )

    markup.add(

        InlineKeyboardButton(
            "📊 Global Health",
            callback_data="server_ping",
        ),

        InlineKeyboardButton(
            "🌐 All Bots",
            callback_data="list_all_bots",
        ),

        InlineKeyboardButton(
            f"🛠 Maintenance: {status}",
            callback_data="toggle_maintenance",
        ),

        InlineKeyboardButton(
            "🚨 Emergency Stop",
            callback_data="emergency_kill",
        ),

        InlineKeyboardButton(
            "🧹 Deep Clean",
            callback_data="server_clean",
        ),

        InlineKeyboardButton(
            "📢 Broadcast",
            callback_data="broadcast_menu",
        ),

        InlineKeyboardButton(
            "📦 Full Backup",
            callback_data="export_zip",
        ),

        InlineKeyboardButton(
            "🔙 Dashboard",
            callback_data="main_menu",
        ),
    )

    return markup


def get_control_panel(
    bot_id,
    running=None,
):

    data = hosted_processes.get(
        bot_id
    )

    if data is None:

        return InlineKeyboardMarkup(
            row_width=2
        )

    if running is None:
        running = is_bot_running(
            bot_id
        )

    markup = InlineKeyboardMarkup(
        row_width=2
    )

    if running:

        markup.add(
            InlineKeyboardButton(
                "🛑 Stop",
                callback_data=f"stop:{bot_id}",
            ),
            InlineKeyboardButton(
                "🔄 Restart",
                callback_data=f"restart_confirm:{bot_id}",
            ),
        )

    else:

        markup.add(
            InlineKeyboardButton(
                "▶️ Start",
                callback_data=f"start:{bot_id}",
            ),
            InlineKeyboardButton(
                "🩺 Health Check",
                callback_data=f"health:{bot_id}",
            ),
        )

    markup.add(

        InlineKeyboardButton(
            "📊 Health",
            callback_data=f"health:{bot_id}",
        ),

        InlineKeyboardButton(
            "📜 Logs",
            callback_data=f"log:{bot_id}",
        ),

        InlineKeyboardButton(
            "📝 Update Code",
            callback_data=f"edit_code:{bot_id}",
        ),

        InlineKeyboardButton(
            "🔐 ENV / Token",
            callback_data=f"bot_env:{bot_id}",
        ),

        InlineKeyboardButton(
            "🕘 Versions",
            callback_data=f"versions:{bot_id}",
        ),

        InlineKeyboardButton(
            "↩️ Rollback",
            callback_data=f"rollback_menu:{bot_id}",
        ),

        InlineKeyboardButton(
            "🗑️ Delete",
            callback_data=f"del:{bot_id}",
        ),

        InlineKeyboardButton(
            "🔙 Dashboard",
            callback_data="main_menu",
        ),
    )

    return markup


# ============================================================
# STATUS BAR
# ============================================================

def build_bot_status_bar(bot_id):
    status = get_bot_status(bot_id)
    health = inspect_bot_health(bot_id)
    metrics = ensure_metrics(bot_id)
    memory = health.get("memory", 0)
    runtime = deployment_runtime.get(bot_id, {})
    process_data = hosted_processes.get(bot_id, {})
    disk = shutil.disk_usage("/")
    queue_depth = deployment_queue.qsize()
    return (
        f"🤖 **{bot_id} STATUS BAR — ADVANCED**\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Status: `{status['status']}`\n"
        f"🆔 PID: `{status['pid'] or '-'}`\n"
        f"🐍 Runtime: `{'ISOLATED .venv' if process_data.get('isolated_env') else 'HOST PYTHON'}`\n"
        f"⏱ Uptime: `{status['uptime']}`\n"
        f"🧠 CPU: `{round(health.get('cpu', 0), 1)}%`\n"
        f"💾 RAM: `{get_readable_size(memory)}`\n"
        f"📈 Peak RAM: `{get_readable_size(metrics.get('peak_memory', 0))}`\n"
        f"💽 Disk Free: `{get_readable_size(disk.free)}`\n"
        f"🔄 Restarts: `{metrics.get('restarts', 0)}`\n"
        f"💥 Crashes: `{metrics.get('crashes', 0)}`\n"
        f"❌ Errors: `{metrics.get('errors', 0)}`\n"
        f"🚀 Starts: `{metrics.get('starts', 0)}`\n"
        f"🛑 Stops: `{metrics.get('stops', 0)}`\n"
        f"📦 Deploy Queue: `{queue_depth}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 **Deployment**\n"
        f"Stage: `{runtime.get('stage') if runtime.get('stage') is not None else 'IDLE'}`\n"
        f"Progress: `{float(runtime.get('percent')):.0f}%`\n"
        f"Package: `{runtime.get('package') or '-'}`\n"
        f"Package progress: `{runtime.get('package_percent') if runtime.get('package_percent') is not None else '-'}`\n"
        f"Last event: `{safe_text(runtime.get('last_event', 'No active deployment'), 220)}`\n"
        f"━━━━━━━━━━━━━━━━━━"
    )


# ============================================================
# START COMMAND
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start_cmd(message):

    user_id = message.from_user.id

    if is_banned(user_id):
        return

    user_chats.add(
        message.chat.id
    )

    save_registry()

    if (
        MAINTENANCE_MODE
        and not is_admin(user_id)
    ):

        bot.send_message(
            message.chat.id,
            (
                "🛠 **SERVER UNDER MAINTENANCE**\n\n"
                "Please try again later."
            ),
            parse_mode="Markdown",
        )

        return

    mtproto_status = (
        "🟢 ACTIVE"
        if MTPROTO_AVAILABLE
        else "🔴 OFFLINE"
    )

    dashboard = (
        "⚡ **PYTHON HOSTING ENGINE** ⚡\n\n"
        f"🆔 **Your ID:** `{user_id}`\n"
        f"🔰 **Access:** "
        f"`{'MASTER ADMIN' if is_admin(user_id) else 'STANDARD'}`\n\n"
        f"🚀 **MTProto:** `{mtproto_status}`\n"
        f"🤖 **Hosted Bots:** `{len(hosted_processes)}`\n"
        f"🟢 **Running:** `"
        f"{sum(is_bot_running(x) for x in hosted_processes)}`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🛡 Duplicate protection: `ACTIVE`\n"
        "🩺 Health watchdog: `ACTIVE`\n"
        "💾 Atomic registry: `ACTIVE`\n"
        "📊 Metrics engine: `ACTIVE`\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Select an operation:"
    )

    bot.send_message(
        message.chat.id,
        dashboard,
        parse_mode="Markdown",
        reply_markup=get_user_menu(
            user_id
        ),
    )


def show_bot_env_by_id(message, user_id):
    bot_id = (message.text or "").strip()
    record = hosted_processes.get(bot_id)
    if not record:
        bot.send_message(message.chat.id, "❌ Bot not found.")
        return
    owner = int(record.get("owner_id", -1))
    if not is_admin(user_id) and owner != int(user_id):
        bot.send_message(message.chat.id, "❌ Access denied.")
        return
    store = bot_envs.get(str(bot_id), {})
    if not store:
        text = f"🔐 **{bot_id} ENV**\n\nNo bot-specific variables saved."
    else:
        text = f"🔐 **{bot_id} ENV**\n\n" + "\n".join(
            f"🟢 `{k}` → `{_mask_secret(str(v))}`" for k, v in store.items()
        )
    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown",
        reply_markup=env_menu_markup(),
    )


# ============================================================
# CALLBACK ROUTER
# ============================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def handle_callbacks(call):

    global MAINTENANCE_MODE

    uid = call.from_user.id
    chat = call.message.chat.id
    data = call.data

    user_chats.add(
        chat
    )

    try:
        bot.answer_callback_query(
            call.id
        )
    except Exception:
        pass

    if data == "main_menu":

        bot.edit_message_text(
            "🎛️ **XX Root Dashboard**\n\n"
            "Choose an operation:",
            chat,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=get_user_menu(
                uid
            ),
        )

        return

    if data == "system_requirements":
        show_system_requirements(chat, uid)
        return

    if data == "sysreq_list":
        if not is_admin(uid):
            return
        _send_system_installed_list(chat)
        return

    if data == "sysreq_managed":
        if not is_admin(uid):
            return
        _send_system_managed_list(chat)
        return

    if data == "sysreq_refresh":
        show_system_requirements(chat, uid)
        return

    if data == "sysreq_add":
        if not is_admin(uid):
            return
        bot.send_message(
            chat,
            "➕ **Add System Requirements**\n\nPaste requirements.txt content, one package per line, or send a `requirements.txt` file.\n\nAlready-satisfied requirements will be skipped automatically.\nType `cancel` to stop.",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(call.message, system_requirements_input)
        return

    if data == "admin_panel":

        if not is_admin(uid):
            return

        bot.edit_message_text(
            "👑 **MASTER ADMIN CONTROL PANEL**",
            chat,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=get_admin_menu(),
        )

        return

    if data == "search_hub":

        bot.edit_message_text(
            "🔍 **Identity Search Hub**",
            chat,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=get_search_hub_menu(),
        )

        return

    if data == "host_file":

        if (
            MAINTENANCE_MODE
            and not is_admin(uid)
        ):

            bot.answer_callback_query(
                call.id,
                "Maintenance is active.",
                show_alert=True,
            )

            return

        bot.send_message(
            chat,
            (
                "📂 **NEW BOT DEPLOYMENT**\n\n"
                "Send a `.py` file, `.zip` project, paste Python source, or write it directly.\n\n"
                "If the requested BOT already exists and "
                "is running, the engine will NOT create "
                "a duplicate process.\n\n"
                "Type `cancel` to abort."
            ),
            parse_mode="Markdown",
        )

        bot.register_next_step_handler(
            call.message,
            process_script_upload,
        )

        return

    if data == "search_by_id":

        bot.send_message(
            chat,
            (
                "🔍 Enter Bot ID.\n"
                "Example: `BOT-1234`"
            ),
            parse_mode="Markdown",
        )

        bot.register_next_step_handler(
            call.message,
            process_search_bot,
        )

        return

    if data.startswith(
        "pkg_auto:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        queued, message = enqueue_deployment({
            "chat_id": chat,
            "msg_id": call.message.message_id,
            "bot_id": bot_id,
            "install_type": "auto",
        })
        bot.send_message(chat, f"{'📥' if queued else '⚠️'} `{bot_id}`: {message}", parse_mode="Markdown")

        return

    if data.startswith(
        "pkg_manual:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        bot.edit_message_text(
            (
                "📝 **Manual Dependency Mode**\n\n"
                "Send `requirements.txt` or package names.\n"
                "Type `cancel` to abort."
            ),
            chat,
            call.message.message_id,
            parse_mode="Markdown",
        )

        bot.register_next_step_handler(
            call.message,
            lambda m: handle_manual_reqs(
                m,
                bot_id,
            ),
        )

        return

    if data == "toggle_maintenance":

        if not is_admin(uid):
            return

        MAINTENANCE_MODE = (
            not MAINTENANCE_MODE
        )

        save_registry()

        bot.edit_message_reply_markup(
            chat,
            call.message.message_id,
            reply_markup=get_admin_menu(),
        )

        return

    if data == "server_ping":

        if psutil:

            cpu = psutil.cpu_percent(
                interval=0.3
            )

            ram = psutil.virtual_memory()

            ram_percent = ram.percent

        else:

            cpu = 0
            ram_percent = 0

        total_disk, used_disk, free_disk = (
            shutil.disk_usage("/")
        )

        running = sum(
            is_bot_running(
                bot_id
            )
            for bot_id
            in hosted_processes
        )

        health_text = (
            "📊 **ADVANCED ENGINE HEALTH**\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"⏱ Uptime: `{get_readable_uptime(time.time() - engine_start_time)}`\n"
            f"🤖 Total Bots: `{len(hosted_processes)}`\n"
            f"🟢 Running: `{running}`\n"
            f"🖥 CPU: `{round(cpu, 1)}%`\n"
            f"💾 RAM: `{ram_percent}%`\n"
            f"💽 Disk Used: `{get_readable_size(used_disk)}`\n"
            f"💽 Disk Free: `{get_readable_size(free_disk)}`\n"
            f"🚀 MTProto: `{'ACTIVE' if MTPROTO_AVAILABLE else 'OFFLINE'}`\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🛡 Single Instance: `ACTIVE`\n"
            "🩺 Watchdog: `ACTIVE`\n"
            "💾 Atomic Registry: `ACTIVE`\n"
            "🧠 TTL/LRU Cache: `ACTIVE`\n"
            "🔁 Retry Manager: `ACTIVE`"
        )

        bot.send_message(
            chat,
            health_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="main_menu",
                )
            ),
        )

        return

    if data == "manage_env":

        show_env_manager(chat, uid)
        return

    if data == "env_add":
        bot.send_message(chat, "➕ Send one or many variables as `KEY=VALUE`. Paste is supported. Type `cancel` to stop.", parse_mode="Markdown")
        bot.register_next_step_handler(call.message, env_add_input)
        return

    if data == "env_list":
        env_list(chat, uid)
        return

    if data == "env_search":
        bot.send_message(chat, "🔎 Enter variable name/search text:")
        bot.register_next_step_handler(call.message, env_search_input)
        return

    if data == "env_update":
        bot.send_message(chat, "✏️ Enter the variable name to update:")
        bot.register_next_step_handler(call.message, lambda m: env_name_input(m, "update"))
        return

    if data == "env_delete":
        bot.send_message(chat, "🗑 Enter the variable name to delete:")
        bot.register_next_step_handler(call.message, lambda m: env_name_input(m, "delete"))
        return

    if data == "env_import":
        bot.send_message(chat, "📥 Paste `.env` content or send an ENV text file. Use `KEY=VALUE` lines.")
        bot.register_next_step_handler(call.message, env_add_input)
        return

    if data == "env_export":
        env_export(chat, uid)
        return

    if data == "env_check":
        env_start_check(chat, uid)
        return

    if data == "env_bot_pick":
        bot.send_message(chat, "🤖 Enter Bot ID for its ENV view:")
        bot.register_next_step_handler(call.message, lambda m: show_bot_env_by_id(m, uid))
        return

    if data.startswith(
        "bot_env:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        data_record = hosted_processes.get(
            bot_id
        )

        if not data_record:
            return

        owner_id = data_record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        envs = user_custom_envs.get(
            str(owner_id),
            {},
        )

        names = (
            "\n".join(
                f"🔹 `{k}` → `********`"
                for k in envs
            )
            if envs
            else "No custom variables."
        )

        bot.send_message(
            chat,
            (
                f"🔐 **{bot_id} ENV MANAGER**\n\n"
                f"{names}\n\n"
                "Use the main ENV manager to add/update variables."
            ),
            parse_mode="Markdown",
        )

        return

    if data == "server_clean":

        if not is_admin(uid):
            return

        shutil.rmtree(
            TEMP_DIR,
            ignore_errors=True,
        )

        os.makedirs(
            TEMP_DIR,
            exist_ok=True,
        )

        for root, _, files in os.walk(
            LOG_DIR
        ):

            for filename in files:

                path = os.path.join(
                    root,
                    filename,
                )

                try:

                    if (
                        os.path.getsize(path)
                        > MAX_LOG_BYTES
                    ):

                        rotate_log_if_needed(
                            filename.replace(
                                ".log",
                                "",
                            )
                        )

                except Exception:
                    continue

        status_cache.clear()

        bot.send_message(
            chat,
            "🧹 **Deep system cleanup completed.**",
            parse_mode="Markdown",
        )

        return

    if data == "browse_files":

        markup = InlineKeyboardMarkup(
            row_width=1
        )

        markup.add(
            InlineKeyboardButton(
                "📦 Export Full Archive",
                callback_data="export_zip",
            ),
            InlineKeyboardButton(
                "🔙 Dashboard",
                callback_data="main_menu",
            ),
        )

        bot.send_message(
            chat,
            "📂 **Storage & Backup Center**",
            parse_mode="Markdown",
            reply_markup=markup,
        )

        return

    if data == "export_zip":

        if not is_admin(uid):

            bot.send_message(
                chat,
                "❌ Backup export is restricted to admin.",
            )

            return

        zip_path = os.path.join(
            TEMP_DIR,
            f"backup_{uid}.zip",
        )

        try:

            with zipfile.ZipFile(
                zip_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:

                for root, _, files in os.walk(
                    HOST_DIR
                ):

                    for filename in files:

                        source = os.path.join(
                            root,
                            filename,
                        )

                        archive.write(
                            source,
                            arcname=os.path.relpath(
                                source,
                                HOST_DIR,
                            ),
                        )

            size = os.path.getsize(
                zip_path
            )

            if (
                size > 49 * 1024 * 1024
                and MTPROTO_AVAILABLE
            ):

                bot.send_message(
                    chat,
                    (
                        f"📦 Archive: `{get_readable_size(size)}`\n"
                        "🚀 Sending through MTProto."
                    ),
                    parse_mode="Markdown",
                )

                threading.Thread(
                    target=mtproto_upload,
                    args=(
                        chat,
                        zip_path,
                        "📦 XX Engine Backup",
                    ),
                    daemon=True,
                ).start()

            else:

                with open(
                    zip_path,
                    "rb",
                ) as document:

                    bot.send_document(
                        chat,
                        document,
                    )

                os.remove(
                    zip_path
                )

        except Exception as exc:

            bot.send_message(
                chat,
                f"❌ Backup failed: `{safe_text(exc)}`",
                parse_mode="Markdown",
            )

        return

    if data in (
        "my_bots",
        "list_all_bots",
    ):

        if (
            data == "list_all_bots"
            and not is_admin(uid)
        ):
            return

        items = []

        for bot_id, record in (
            hosted_processes.items()
        ):

            owner_id = record.get(
                "owner_id"
            )

            if (
                is_admin(uid)
                or int(owner_id) == int(uid)
            ):

                items.append(
                    (
                        bot_id,
                        record,
                    )
                )

        if not items:

            bot.send_message(
                chat,
                "📂 No bots found.",
                reply_markup=get_user_menu(
                    uid
                ),
            )

            return

        markup = InlineKeyboardMarkup(
            row_width=1
        )

        for bot_id, record in items:

            running = is_bot_running(
                bot_id
            )

            status = (
                "🟢"
                if running
                else "🔴"
            )

            markup.add(
                InlineKeyboardButton(
                    (
                        f"{status} "
                        f"{bot_id} "
                        f"({os.path.basename(record['entry_file'])})"
                    ),
                    callback_data=f"manage:{bot_id}",
                )
            )

        markup.add(
            InlineKeyboardButton(
                "➕ Deploy New Bot",
                callback_data="host_file",
            ),
            InlineKeyboardButton(
                "🔙 Dashboard",
                callback_data="main_menu",
            ),
        )

        bot.send_message(
            chat,
            "🤖 **BOT CONTROL CENTER**",
            parse_mode="Markdown",
            reply_markup=markup,
        )

        return

    if data.startswith(
        "manage:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            bot.answer_callback_query(
                call.id,
                "Bot not found.",
                show_alert=True,
            )
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        text = build_bot_status_bar(
            bot_id
        )

        bot.send_message(
            chat,
            text,
            parse_mode="Markdown",
            reply_markup=get_control_panel(
                bot_id
            ),
        )

        return

    if data.startswith(
        "health:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        health = inspect_bot_health(
            bot_id
        )

        text = (
            f"🩺 **{bot_id} HEALTH PANEL**\n\n"
            f"Status: `{health['status']}`\n"
            f"PID: `{health.get('pid') or '-'}`\n"
            f"CPU: `{round(health.get('cpu', 0), 1)}%`\n"
            f"RAM: `{get_readable_size(health.get('memory', 0))}`\n\n"
            f"{build_bot_status_bar(bot_id)}"
        )

        bot.send_message(
            chat,
            text,
            parse_mode="Markdown",
            reply_markup=get_control_panel(
                bot_id
            ),
        )

        return

    if data.startswith(
        "restart_confirm:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        markup = InlineKeyboardMarkup(
            row_width=2
        )

        markup.add(
            InlineKeyboardButton(
                "✅ Confirm Restart",
                callback_data=f"restart:{bot_id}",
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=f"manage:{bot_id}",
            ),
        )

        bot.send_message(
            chat,
            (
                f"⚠️ `{bot_id}` is currently running.\n\n"
                "A restart will stop the existing process "
                "and start exactly one replacement process."
            ),
            parse_mode="Markdown",
            reply_markup=markup,
        )

        return

    if data.startswith(
        "start:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        result = start_bot_once(
            bot_id,
            record["entry_file"],
            owner_id,
            reason="manual_start",
            notify=False,
        )

        bot.send_message(
            chat,
            result["message"],
            parse_mode="Markdown",
            reply_markup=get_control_panel(
                bot_id
            ),
        )

        return

    if data.startswith(
        "restart:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        result = restart_bot(
            bot_id,
            owner_id,
            notify=False,
        )

        bot.send_message(
            chat,
            result["message"],
            parse_mode="Markdown",
            reply_markup=get_control_panel(
                bot_id
            ),
        )

        return

    if data.startswith(
        "stop:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        stop_script_process(
            bot_id,
            reason="manual_stop",
        )

        bot.send_message(
            chat,
            (
                f"🛑 `{bot_id}` stopped.\n\n"
                "No automatic restart will occur "
                "until you explicitly start it."
            ),
            parse_mode="Markdown",
            reply_markup=get_control_panel(
                bot_id,
                running=False,
            ),
        )

        return

    if data.startswith(
        "log:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        path = record.get(
            "log_file"
        )

        content = (
            "No logs yet."
        )

        if path and os.path.exists(
            path
        ):

            with open(
                path,
                "r",
                encoding="utf-8",
                errors="ignore",
            ) as handle:

                content = handle.read()[
                    -30000:
                ]

        bot.send_message(
            chat,
            f"📜 **{bot_id} LIVE LOGS**",
            parse_mode="Markdown",
        )

        send_long_message(
            chat,
            content,
            is_code=True,
        )

        return

    if data.startswith(
        "edit_code:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        bot.send_message(
            chat,
            (
                f"📝 **{bot_id} CODE UPDATE**\n\n"
                "Send the new Python code or a Python document.\n"
                "A version backup will be created automatically.\n\n"
                "Type `cancel` to abort."
            ),
            parse_mode="Markdown",
        )

        bot.register_next_step_handler(
            call.message,
            lambda m: save_edited_code(
                m,
                bot_id,
            ),
        )

        return

    if data.startswith(
        "versions:"
    ):

        bot_id = data.split(
            ":",
            1,
        )[1]

        versions = bot_versions.get(
            bot_id,
            [],
        )

        if not versions:

            bot.send_message(
                chat,
                "🕘 No versions stored.",
            )

            return

        markup = InlineKeyboardMarkup(
            row_width=1
        )

        for item in reversed(
            versions[-10:]
        ):

            version = item.get(
                "version",
                "unknown",
            )

            reason = item.get(
                "reason",
                "update",
            )

            markup.add(
                InlineKeyboardButton(
                    f"🕘 {version} · {reason}",
                    callback_data=(
                        f"rollback_select:"
                        f"{bot_id}:"
                        f"{version}"
                    ),
                )
            )

        markup.add(
            InlineKeyboardButton(
                "🔙 Back",
                callback_data=f"manage:{bot_id}",
            )
        )

        bot.send_message(
            chat,
            f"🕘 **{bot_id} VERSION HISTORY**",
            parse_mode="Markdown",
            reply_markup=markup,
        )

        return

    if data.startswith(
        "rollback_select:"
    ):

        parts = data.split(
            ":",
            2,
        )

        if len(parts) != 3:
            return

        bot_id = parts[1]
        version = parts[2]

        markup = InlineKeyboardMarkup(
            row_width=2
        )

        markup.add(
            InlineKeyboardButton(
                "✅ Confirm Rollback",
                callback_data=(
                    f"rollback:{bot_id}:{version}"
                ),
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=f"manage:{bot_id}",
            ),
        )

        bot.send_message(
            chat,
            (
                f"⚠️ Roll back `{bot_id}` to\n"
                f"`{version}`?"
            ),
            parse_mode="Markdown",
            reply_markup=markup,
        )

        return

    if data.startswith(
        "rollback:"
    ):

        parts = data.split(
            ":",
            2,
        )

        if len(parts) != 3:
            return

        bot_id = parts[1]
        version = parts[2]

        record = hosted_processes.get(
            bot_id
        )

        if not record:
            return

        owner_id = record.get(
            "owner_id"
        )

        if (
            not is_admin(uid)
            and int(owner_id) != int(uid)
        ):
            return

        ok, message = rollback_bot(
            bot_id,
            version,
            owner_id,
        )

        bot.send_message(
            chat,
            (
                "✅ "
                if ok
                else "❌ "
            )
            + message,
            parse_mode="Markdown",
            reply_markup=get_control_panel(
                bot_id
            ),
        )

        return

    if data.startswith(
        "del:"
    ):

        if not is_admin(uid):
            return

        bot_id = data.split(
            ":",
            1,
        )[1]

        record = hosted_processes.get(
            bot_id
        )

        if record:
            stop_script_process(
                bot_id,
                reason="delete",
            )

        shutil.rmtree(
            os.path.join(
                HOST_DIR,
                bot_id,
            ),
            ignore_errors=True,
        )

        hosted_processes.pop(
            bot_id,
            None,
        )

        bot_metadata.pop(
            bot_id,
            None,
        )

        bot_versions.pop(
            bot_id,
            None,
        )

        bot_metrics.pop(
            bot_id,
            None,
        )

        save_registry()

        bot.send_message(
            chat,
            f"🗑️ `{bot_id}` deleted.",
            parse_mode="Markdown",
        )

        return

    if data == "stop_my_bots":

        count = 0

        for bot_id, record in list(
            hosted_processes.items()
        ):

            if int(
                record.get(
                    "owner_id",
                    -1,
                )
            ) == int(uid):

                if is_bot_running(
                    bot_id
                ):

                    stop_script_process(
                        bot_id,
                        reason="user_stop_all",
                    )

                    count += 1

        bot.send_message(
            chat,
            (
                f"🛑 Stopped `{count}` bot(s).\n"
                "Automatic recovery is disabled for "
                "manually stopped bots."
            ),
            parse_mode="Markdown",
        )

        return

    if data == "emergency_kill":

        if not is_admin(uid):
            return

        for bot_id in list(
            hosted_processes.keys()
        ):

            stop_script_process(
                bot_id,
                reason="admin_emergency_stop",
            )

        bot.send_message(
            chat,
            (
                "🚨 **EMERGENCY STOP COMPLETE**\n\n"
                "All hosted processes were stopped."
            ),
            parse_mode="Markdown",
        )

        return


# ============================================================
# DEPLOYMENT UPLOAD
# ============================================================

def process_script_upload(
    message
):

    if (
        message.text
        and message.text.lower()
        == "cancel"
    ):

        bot.send_message(
            message.chat.id,
            "❌ Deployment cancelled.",
        )

        return

    user_id = message.from_user.id

    if (
        not message.document
        and not message.text
    ):

        bot.send_message(
            message.chat.id,
            "❌ Send Python source or a `.py`/`.zip` file.",
        )

        return

    bot_id = generate_bot_id()

    bot_dir = os.path.join(
        HOST_DIR,
        bot_id,
    )

    os.makedirs(
        bot_dir,
        exist_ok=True,
    )

    start_time = time.time()

    progress = bot.send_message(
        message.chat.id,
        (
            f"🔄 **Initializing {bot_id}**\n\n"
            "`[░░░░░░░░░░] 0%`"
        ),
        parse_mode="Markdown",
    )

    try:

        if message.text:
            if len(message.text.encode("utf-8")) > MAX_SOURCE_TEXT_BYTES:
                raise ResourceLimitError("Source text exceeds configured upload limit.")

            entry_file = "main.py"

            with open(
                os.path.join(
                    bot_dir,
                    entry_file,
                ),
                "w",
                encoding="utf-8",
            ) as handle:

                handle.write(
                    message.text
                )

        else:

            filename = (
                message.document.file_name
            )

            filename = os.path.basename(
                filename
            )

            file_size = (
                message.document.file_size
                or 0
            )
            if file_size <= 0:
                raise ValueError("Uploaded file size is missing or invalid.")
            if file_size > MAX_UPLOAD_BYTES:
                raise ResourceLimitError(
                    f"Upload exceeds MAX_UPLOAD_BYTES ({MAX_UPLOAD_BYTES} bytes)."
                )

            if not (
                filename.endswith(".py")
                or filename.endswith(".zip")
            ):

                raise ValueError(
                    "Only .py and .zip files are supported."
                )

            if filename.endswith(
                ".zip"
            ):

                target_file = os.path.join(
                    TEMP_DIR,
                    f"{bot_id}.zip",
                )

            else:

                safe_filename = (
                    re.sub(
                        r"[^A-Za-z0-9_.-]",
                        "_",
                        filename,
                    )
                )

                target_file = os.path.join(
                    bot_dir,
                    safe_filename,
                )

            if (
                file_size
                > 20 * 1024 * 1024
                and MTPROTO_AVAILABLE
            ):

                update_hud(
                    message.chat.id,
                    progress.message_id,
                    "MTProto Core",
                    (
                        "Streaming large payload → "
                        f"{get_readable_size(file_size)}"
                    ),
                    30,
                    start_time,
                )

                mtproto_download(
                    message.chat.id,
                    message.message_id,
                    target_file,
                )

            else:

                update_hud(
                    message.chat.id,
                    progress.message_id,
                    "Telegram Core",
                    "Downloading payload...",
                    20,
                    start_time,
                )

                file_info = bot.get_file(
                    message.document.file_id
                )

                downloaded = bot.download_file(
                    file_info.file_path
                )

                with open(
                    target_file,
                    "wb",
                ) as handle:

                    handle.write(
                        downloaded
                    )

            if filename.endswith(
                ".zip"
            ):

                update_hud(
                    message.chat.id,
                    progress.message_id,
                    "Project Extractor",
                    "Validating and extracting ZIP...",
                    45,
                    start_time,
                )

                safe_extract_zip(
                    target_file,
                    bot_dir,
                    max_compressed_bytes=MAX_UPLOAD_BYTES,
                    max_uncompressed_bytes=MAX_BOT_DISK_BYTES,
                    max_files=MAX_PROJECT_FILES,
                )

                os.remove(
                    target_file
                )

                entry_file = None

                preferred = (
                    "main.py",
                    "bot.py",
                    "app.py",
                )

                for preferred_name in preferred:

                    for root, _, files in os.walk(
                        bot_dir
                    ):

                        if preferred_name in files:

                            entry_file = os.path.relpath(
                                os.path.join(
                                    root,
                                    preferred_name,
                                ),
                                bot_dir,
                            )

                            break

                    if entry_file:
                        break

                if not entry_file:
                    candidates = []
                    for root, _, names in os.walk(bot_dir):
                        for name in names:
                            if name.endswith(".py") and name != "__init__.py":
                                candidates.append(os.path.relpath(os.path.join(root, name), bot_dir))
                    if len(candidates) == 1:
                        entry_file = candidates[0]
                    elif candidates:
                        # Prefer files containing a normal executable main guard.
                        scored = []
                        for candidate in candidates:
                            score = 0
                            try:
                                txt = Path(bot_dir, candidate).read_text(encoding="utf-8", errors="ignore")
                                if "if __name__" in txt:
                                    score += 5
                                if "Flask(" in txt or "FastAPI(" in txt or "asyncio.run(" in txt:
                                    score += 3
                                if "def main(" in txt:
                                    score += 2
                            except Exception:
                                pass
                            scored.append((score, candidate))
                        entry_file = max(scored)[1]
                    else:
                        raise ValueError("ZIP does not contain a Python script.")

            else:

                entry_file = os.path.basename(
                    target_file
                )

        user_deploy_states[bot_id] = {
            "owner_id": user_id,
            "entry_file": entry_file,
            "msg_id": progress.message_id,
            "start_time": start_time,
        }

        requirements_path = os.path.join(
            bot_dir,
            "requirements.txt",
        )

        if os.path.exists(
            requirements_path
        ):

            queued, queue_message = enqueue_deployment({
                "chat_id": message.chat.id,
                "msg_id": progress.message_id,
                "bot_id": bot_id,
                "install_type": "manual",
                "manual_req_path": requirements_path,
            })
            bot.send_message(message.chat.id, f"{'📦' if queued else '⚠️'} `{bot_id}`: {queue_message}", parse_mode="Markdown")

            return

        bot.edit_message_text(
            (
                f"📦 **Secure Node Locked:** `{bot_id}`\n\n"
                "Choose dependency protocol:"
            ),
            message.chat.id,
            progress.message_id,
            parse_mode="Markdown",
            reply_markup=get_package_menu(
                bot_id
            ),
        )

    except Exception as exc:

        logger.exception(
            "Upload failed."
        )

        shutil.rmtree(
            bot_dir,
            ignore_errors=True,
        )

        user_deploy_states.pop(
            bot_id,
            None,
        )

        bot.edit_message_text(
            (
                "❌ **Deployment Failed**\n\n"
                f"`{redact_sensitive_text(exc, 2000)}`"
            ),
            message.chat.id,
            progress.message_id,
            parse_mode="Markdown",
        )


# ============================================================
# DEPLOYMENT FINALIZATION
# ============================================================

def finalize_deployment(
    chat_id,
    msg_id,
    bot_id,
    install_type,
    manual_req_path=None,
    skip_dependencies=False,
):

    state = user_deploy_states.get(
        bot_id
    )

    if not state:
        return

    user_id = state["owner_id"]
    entry_file = state["entry_file"]
    start_time = state["start_time"]

    bot_dir = os.path.join(
        HOST_DIR,
        bot_id,
    )

    script_path = os.path.join(
        bot_dir,
        entry_file,
    )

    try:

        # Ultra-Promax security preflight: validate before activation.
        security_report = _hardened_deployment_preflight(bot_id)
        if security_report.get("risk") == "CRITICAL":
            raise SecurityError("Security preflight blocked deployment.")

        if not os.path.isfile(
            script_path
        ):
            raise FileNotFoundError(
                "Entry file disappeared."
            )

        if (
            install_type == "manual"
            and manual_req_path
            and os.path.exists(
                manual_req_path
            )
        ):

            update_hud(
                chat_id,
                msg_id,
                "Strict Setup HUD",
                "Installing requirements.txt...",
                60,
                start_time,
            )

            python_cmd = _ensure_bot_venv(
                bot_id,
                chat_id,
                msg_id,
                start_time,
            )
            req_count = 0
            try:
                with open(manual_req_path, "r", encoding="utf-8", errors="ignore") as req_handle:
                    req_count = sum(1 for line in req_handle if line.strip() and not line.lstrip().startswith("#"))
            except Exception:
                pass
            state = _deployment_state(bot_id)
            state["package_total"] = req_count
            requirements_args = ["-r", "/workspace/requirements.txt", "--no-cache-dir", "--progress-bar", "on", "--disable-pip-version-check", "--no-input"]
            install_command = (_docker_install_command(bot_id, requirements_args) if SANDBOX_MODE in {"docker", "required"} else [python_cmd, "-m", "pip", "install", "-r", manual_req_path, "--no-cache-dir", "--progress-bar", "on", "--disable-pip-version-check", "--no-input"])
            _pip_stream_install(bot_id, install_command, chat_id, msg_id, start_time, "requirements.txt", 60)
            state["installed"] = req_count
            state["pending"] = 0

        else:

            update_hud(
                chat_id,
                msg_id,
                "AST Dependency HUD",
                "Analyzing imports...",
                50,
                start_time,
            )

            packages = deep_analyze_imports(
                bot_dir
            )

            success, error = (
                auto_install_packages_verified(
                    packages,
                    chat_id,
                    msg_id,
                    start_time,
                    bot_id=bot_id,
                )
            )

            if not success:
                raise RuntimeError(
                    error
                )

        # Final configuration preflight: reuse saved ENV, ask only for missing values.
        if not skip_dependencies:
            required_env = detect_project_env_requirements(bot_dir)
            saved_env = _bot_env_store(bot_id)
            missing_env = [k for k in required_env if not saved_env.get(k, "").strip()]
            if missing_env:
                env_collection_states[bot_id] = {
                    "chat_id": chat_id,
                    "msg_id": msg_id,
                    "owner_id": user_id,
                    "missing": missing_env,
                    "index": 0,
                    "start_time": start_time,
                }
                bot.send_message(
                    chat_id,
                    f"🔐 **Configuration Required**\n\n`{missing_env[0]}`\n\nSend its value. Type `cancel` to stop.",
                    parse_mode="Markdown",
                )
                return

        update_hud(
            chat_id,
            msg_id,
            "Compilation Guard",
            "Checking Python syntax...",
            85,
            start_time,
        )

        py_compile.compile(
            script_path,
            doraise=True,
        )

        result = start_bot_once(
            bot_id,
            entry_file,
            user_id,
            reason="deployment",
            notify=False,
            verify_startup=True,
        )

        if not result["started"]:

            raise RuntimeError(
                "Bot unexpectedly became active before deployment."
            )

        ensure_metrics(
            bot_id
        )["deployments"] += 1

        bot_metadata[bot_id] = {
            "owner_id": user_id,
            "entry_file": entry_file,
            "created_at": bot_metadata.get(
                bot_id,
                {},
            ).get(
                "created_at",
                now_iso(),
            ),
            "last_deployed": now_iso(),
        }

        user_deploy_states.pop(
            bot_id,
            None,
        )

        save_registry()

        _deployment_event(bot_id, "Deployment completed successfully", stage="Deployment Complete", action="BOT 100% Operational", percent=100, package_percent=100, pending=0)
        update_hud(
            chat_id,
            msg_id,
            "XX Deployment HUD",
            "BOT 100% Operational",
            100,
            start_time,
            bot_id=bot_id,
            verified=True,
        )

        bot.send_message(
            chat_id,
            (
                "🚀 **BOT DEPLOYED SUCCESSFULLY**\n\n"
                f"🤖 ID: `{bot_id}`\n"
                f"🟢 Status: `RUNNING`\n"
                f"🆔 PID: `{result['pid']}`\n\n"
                "🛡 Duplicate protection is active.\n"
                "If this same bot is requested again while "
                "running, no second process will be created."
            ),
            parse_mode="Markdown",
            reply_markup=get_control_panel(
                bot_id,
                True,
            ),
        )

    except Exception as exc:

        logger.exception(
            "Final deployment failed."
        )

        record_error(
            bot_id,
            exc,
        )

        bot.send_message(
            chat_id,
            (
                "❌ **Deployment Halted**\n\n"
                f"`{redact_sensitive_text(exc, 2500)}`"
            ),
            parse_mode="Markdown",
        )


# ============================================================
# SEARCH BOT
# ============================================================

def process_search_bot(
    message
):

    if (
        message.text
        and message.text.lower()
        == "cancel"
    ):

        bot.send_message(
            message.chat.id,
            "❌ Search cancelled.",
        )

        return

    query = (
        message.text
        .strip()
        .upper()
    )

    if not query.startswith(
        "BOT-"
    ):

        query = (
            "BOT-"
            + query
        )

    record = hosted_processes.get(
        query
    )

    if not record:

        bot.send_message(
            message.chat.id,
            (
                f"❌ `{query}` was not found.\n\n"
                "➕ You can deploy a new bot instead."
            ),
            parse_mode="Markdown",
            reply_markup=get_user_menu(
                message.from_user.id
            ),
        )

        return

    owner_id = record.get(
        "owner_id"
    )

    if (
        not is_admin(
            message.from_user.id
        )
        and int(owner_id)
        != int(message.from_user.id)
    ):
        return

    if is_bot_running(
        query
    ):

        text = (
            f"🤖 **{query}**\n\n"
            "🟢 **ALREADY RUNNING**\n\n"
            "⚠️ A duplicate process will NOT be created.\n"
            "If you want a restart, choose Restart."
        )

    else:

        text = (
            f"🤖 **{query}**\n\n"
            "🔴 **STOPPED**\n\n"
            "You can start it again."
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown",
        reply_markup=get_control_panel(
            query
        ),
    )


# ============================================================
# CODE UPDATE
# ============================================================

def save_edited_code(
    message,
    bot_id,
):

    if (
        message.text
        and message.text.lower()
        == "cancel"
    ):

        bot.send_message(
            message.chat.id,
            "❌ Update cancelled.",
        )

        return

    record = hosted_processes.get(
        bot_id
    )

    if not record:

        bot.send_message(
            message.chat.id,
            "❌ Bot integrity record not found.",
        )

        return

    owner_id = record.get(
        "owner_id"
    )

    if (
        not is_admin(
            message.from_user.id
        )
        and int(owner_id)
        != int(message.from_user.id)
    ):
        return

    bot_dir = os.path.join(
        HOST_DIR,
        bot_id,
    )

    script_path = os.path.join(
        bot_dir,
        record["entry_file"],
    )

    try:

        create_bot_version(
            bot_id,
            reason="pre_code_update",
        )

        candidate = Path(TEMP_DIR) / f"{bot_id}_code_candidate_{uuid.uuid4().hex}.py"
        if message.document:
            if (message.document.file_size or 0) > MAX_SOURCE_TEXT_BYTES:
                raise ResourceLimitError("Updated source exceeds configured limit.")
            info = bot.get_file(message.document.file_id)
            content = bot.download_file(info.file_path)
            if len(content) > MAX_SOURCE_TEXT_BYTES:
                raise ResourceLimitError("Downloaded source exceeds configured limit.")
            candidate.write_bytes(content)
        elif message.text:
            if len(message.text.encode("utf-8")) > MAX_SOURCE_TEXT_BYTES:
                raise ResourceLimitError("Updated source exceeds configured limit.")
            candidate.write_text(message.text, encoding="utf-8")
        else:
            raise ValueError("No code was supplied.")

        py_compile.compile(str(candidate), doraise=True)
        # Security preflight on the candidate file before it can replace the active code.
        candidate_text = candidate.read_text(encoding="utf-8", errors="ignore")
        candidate_tree = ast.parse(candidate_text, filename=record["entry_file"])
        for node in ast.walk(candidate_tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
                if name in DANGEROUS_CALLS and SECURITY_SCAN_STRICT:
                    raise SecurityError(f"Security preflight blocked dangerous call: {name}")

        previous = Path(TEMP_DIR) / f"{bot_id}_code_previous_{uuid.uuid4().hex}.py"
        shutil.copy2(script_path, previous)
        was_running = is_bot_running(bot_id)
        try:
            if was_running:
                stop_script_process(bot_id, reason="code_update_prepare")
            os.replace(str(candidate), script_path)
            result = start_bot_once(bot_id, owner_id=owner_id, entry_file=record["entry_file"], reason="code_update", notify=False, verify_startup=True)
            if not result.get("started"):
                raise DeploymentError("Updated code did not start successfully.")
            ensure_metrics(bot_id)["successful_runs"] = int(ensure_metrics(bot_id).get("successful_runs", 0)) + 1
        except Exception:
            if os.path.exists(previous):
                try:
                    if is_bot_running(bot_id):
                        stop_script_process(bot_id, reason="code_update_rollback")
                    os.replace(str(previous), script_path)
                    if was_running:
                        start_bot_once(bot_id, owner_id=owner_id, entry_file=record["entry_file"], reason="code_update_rollback", notify=False, verify_startup=True)
                except Exception as rollback_exc:
                    record_error(bot_id, rollback_exc)
            raise
        finally:
            try: candidate.unlink(missing_ok=True)
            except Exception: pass
            try: previous.unlink(missing_ok=True)
            except Exception: pass

        bot.send_message(
            message.chat.id,
            (
                f"✅ **{bot_id} UPDATED**\n\n"
                "🧾 Previous version was backed up.\n"
                "🔄 One controlled restart completed.\n"
                "🛡 Duplicate process protection remains active."
            ),
            parse_mode="Markdown",
            reply_markup=get_control_panel(
                bot_id,
                True,
            ),
        )

    except Exception as exc:

        record_error(
            bot_id,
            exc,
        )

        bot.send_message(
            message.chat.id,
            (
                "❌ **Code Update Failed**\n\n"
                f"`{redact_sensitive_text(exc, 2000)}`"
            ),
            parse_mode="Markdown",
        )


# ============================================================
# ENVIRONMENT VARIABLE
# ============================================================

def save_env_var(
    message
):

    if (
        not message.text
    ):

        bot.send_message(
            message.chat.id,
            "❌ Send KEY=VALUE.",
        )

        return

    if (
        message.text.lower()
        == "cancel"
    ):

        bot.send_message(
            message.chat.id,
            "❌ Cancelled.",
        )

        return

    try:

        key, value = (
            message.text.split(
                "=",
                1,
            )
        )

        key = key.strip()
        value = value.strip()

        if not re.match(
            r"^[A-Za-z_][A-Za-z0-9_]*$",
            key,
        ):
            raise ValueError(
                "Invalid environment variable name."
            )

        user_custom_envs.setdefault(
            str(message.from_user.id),
            {},
        )[key] = value

        save_registry()

        bot.send_message(
            message.chat.id,
            (
                "✅ **ENV SAVED**\n\n"
                f"🔑 `{key}`\n"
                "🔒 Value stored securely and masked in UI."
            ),
            parse_mode="Markdown",
        )

    except Exception as exc:

        bot.send_message(
            message.chat.id,
            (
                "❌ Invalid format.\n"
                "Use `KEY=VALUE`."
            ),
            parse_mode="Markdown",
        )


# ============================================================
# DEPLOYMENT ENV COLLECTION
# ============================================================

def receive_deploy_env(message):
    # Locate the user's active deployment waiting for configuration.
    target = None
    for bot_id, state in list(env_collection_states.items()):
        if int(state.get("owner_id", -1)) == int(message.from_user.id) and int(state.get("chat_id", -1)) == int(message.chat.id):
            target = bot_id
            break
    if not target:
        return
    state = env_collection_states[target]
    if message.text and message.text.lower().strip() == "cancel":
        env_collection_states.pop(target, None)
        bot.send_message(message.chat.id, "❌ Deployment cancelled.")
        return
    values = parse_env_text(message.text or "")
    key = state["missing"][state["index"]]
    if key in values and values[key]:
        value = values[key]
    else:
        value = (message.text or "").strip()
    if not value:
        bot.send_message(message.chat.id, f"❌ Empty value. Please send `{key}` value.", parse_mode="Markdown")
        bot.register_next_step_handler(message, receive_deploy_env)
        return
    save_bot_env_values(target, {key: value})
    state["index"] += 1
    if state["index"] < len(state["missing"]):
        next_key = state["missing"][state["index"]]
        bot.send_message(message.chat.id, f"🔐 **Configuration {state['index'] + 1}/{len(state['missing'])}**\n\n`{next_key}`\n\nSend its value.", parse_mode="Markdown")
        bot.register_next_step_handler(message, receive_deploy_env)
        return
    chat_id = state["chat_id"]
    msg_id = state["msg_id"]
    bot_id = target
    start_time = state["start_time"]
    env_collection_states.pop(bot_id, None)
    bot.send_message(chat_id, "✅ Configuration complete. Running final validation…")
    queued, queue_message = enqueue_deployment({
        "chat_id": chat_id,
        "msg_id": msg_id,
        "bot_id": bot_id,
        "install_type": "resume",
        "skip_dependencies": True,
    })
    if not queued:
        bot.send_message(chat_id, f"⚠️ `{bot_id}`: {queue_message}", parse_mode="Markdown")
        return


# ============================================================
# MANUAL REQUIREMENTS
# ============================================================

def handle_manual_reqs(
    message,
    bot_id,
):

    if (
        message.text
        and message.text.lower()
        == "cancel"
    ):

        bot.send_message(
            message.chat.id,
            "❌ Dependency setup cancelled.",
        )

        return

    bot_dir = os.path.join(
        HOST_DIR,
        bot_id,
    )

    req_path = os.path.join(
        bot_dir,
        "requirements.txt",
    )

    try:

        if message.document:

            info = bot.get_file(
                message.document.file_id
            )

            content = bot.download_file(
                info.file_path
            )

            with open(
                req_path,
                "wb",
            ) as handle:

                handle.write(
                    content
                )

        elif message.text:

            requirements = (
                message.text.replace(
                    ",",
                    "\n",
                )
            )

            with open(
                req_path,
                "w",
                encoding="utf-8",
            ) as handle:

                handle.write(
                    requirements
                )

        else:

            raise ValueError(
                "No requirements supplied."
            )

        state = user_deploy_states.get(
            bot_id
        )

        if not state:
            raise ValueError(
                "Deployment state expired."
            )

        progress = bot.send_message(
            message.chat.id,
            "📥 Added to deployment queue...",
        )

        queued, queue_message = enqueue_deployment({
            "chat_id": message.chat.id,
            "msg_id": progress.message_id,
            "bot_id": bot_id,
            "install_type": "manual",
            "manual_req_path": req_path,
        })
        if not queued:
            raise DeploymentError(queue_message)

    except Exception as exc:

        bot.send_message(
            message.chat.id,
            f"❌ `{safe_text(exc)}`",
            parse_mode="Markdown",
        )


# ============================================================
# BROADCAST
# ============================================================

def process_broadcast(
    message
):

    if (
        message.text
        and message.text.lower()
        == "cancel"
    ):

        bot.send_message(
            message.chat.id,
            "❌ Broadcast cancelled.",
        )

        return

    if not is_admin(
        message.from_user.id
    ):
        return

    user_chats.add(
        message.chat.id
    )

    save_registry()

    status = bot.send_message(
        message.chat.id,
        "📢 **Broadcast started.**",
        parse_mode="Markdown",
    )

    def run_broadcast():

        success = 0
        failed = 0

        for target_id in list(
            user_chats
        ):

            try:

                bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )

                success += 1

                time.sleep(
                    0.15
                )

            except Exception:
                failed += 1

        try:

            bot.edit_message_text(
                (
                    "✅ **Broadcast completed**\n\n"
                    f"🟢 Success: `{success}`\n"
                    f"🔴 Failed: `{failed}`"
                ),
                message.chat.id,
                status.message_id,
                parse_mode="Markdown",
                reply_markup=get_admin_menu(),
            )

        except Exception:
            pass

    threading.Thread(
        target=run_broadcast,
        daemon=True,
    ).start()


# ============================================================
# CLEANUP
# ============================================================

def cleanup_engine():

    global SHUTDOWN_REQUESTED

    SHUTDOWN_REQUESTED = True

    logger.info(
        "Graceful shutdown initiated."
    )

    for bot_id in list(
        hosted_processes.keys()
    ):

        try:

            stop_script_process(
                bot_id,
                reason="engine_shutdown",
            )

        except Exception:
            logger.exception(
                "Failed stopping %s",
                bot_id,
            )

    try:
        save_registry()
    except Exception:
        logger.exception(
            "Final registry save failed."
        )

    release_engine_lock()

    logger.info(
        "Graceful shutdown complete."
    )


def signal_handler(
    signum,
    frame,
):

    logger.info(
        "Received signal %s.",
        signum,
    )

    cleanup_engine()


# ============================================================
# WEB HEALTH ENDPOINTS
# ============================================================

@app.route("/")
def home():

    running = sum(
        is_bot_running(
            bot_id
        )
        for bot_id in hosted_processes
    )

    return (
        "⚡ XX Supercharged Hosting Engine Live! "
        f"Active Bots: {running}"
    )


@app.route("/health")
def health():

    if psutil:

        memory = psutil.virtual_memory()

        cpu = psutil.cpu_percent(
            interval=0.05
        )

        memory_percent = memory.percent

    else:

        cpu = 0
        memory_percent = 0

    # Public liveness endpoint intentionally exposes only coarse health.
    # Detailed operational data remains protected by X-Health-Key.
    return jsonify({
        "status": "ok",
        "uptime": get_readable_uptime(time.time() - engine_start_time),
    })


# ============================================================
# DETAILED OBSERVABILITY ENDPOINTS
# ============================================================

@app.route("/health/detailed")
def health_detailed():
    if not HEALTH_API_KEY or not hmac.compare_digest(request.headers.get("X-Health-Key", ""), HEALTH_API_KEY):
        return jsonify({"error": "forbidden"}), 403
    if psutil:
        vm = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.05)
        load = os.getloadavg() if hasattr(os, "getloadavg") else None
    else:
        vm, cpu, load = None, 0, None
    disk = shutil.disk_usage("/")
    return jsonify({
        "status": "ok",
        "engine": {"uptime": get_readable_uptime(time.time() - engine_start_time), "pid": os.getpid(), "workers": len(deployment_workers)},
        "server": {"cpu_percent": cpu, "ram_percent": vm.percent if vm else 0, "ram_used": vm.used if vm else 0, "ram_available": vm.available if vm else 0, "disk_used": disk.used, "disk_free": disk.free, "load_average": load},
        "queue": {"depth": deployment_queue.qsize()},
        "bots": {"total": len(hosted_processes), "running": sum(is_bot_running(x) for x in hosted_processes)},
        "deployments": {bid: {k: (list(v) if k == "events" else v) for k, v in state.items()} for bid, state in deployment_runtime.items()},
    })


@app.route("/deployments")
def deployments_status():
    if not HEALTH_API_KEY or not hmac.compare_digest(request.headers.get("X-Health-Key", ""), HEALTH_API_KEY):
        return jsonify({"error": "forbidden"}), 403
    return jsonify({
        bid: {k: (list(v) if k == "events" else v) for k, v in state.items()}
        for bid, state in deployment_runtime.items()
    })


# ============================================================
# PERIODIC REGISTRY SAVER
# ============================================================

def registry_flush_worker():

    while not SHUTDOWN_REQUESTED:

        time.sleep(
            30
        )

        try:
            save_registry()
        except Exception:
            logger.exception(
                "Periodic registry save failed."
            )


# ============================================================
# STARTUP VALIDATION
# ============================================================

def validate_environment():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is required."
        )

    if not os.path.isdir(
        HOST_DIR
    ):
        os.makedirs(
            HOST_DIR,
            exist_ok=True,
        )

    if not os.path.isdir(
        LOG_DIR
    ):
        os.makedirs(
            LOG_DIR,
            exist_ok=True,
        )

    if not os.path.isdir(
        TEMP_DIR
    ):
        os.makedirs(
            TEMP_DIR,
            exist_ok=True,
        )

    if SANDBOX_MODE in {"docker", "required"} and not _docker_available():
        raise RuntimeError("SANDBOX_MODE requires Docker, but docker executable is unavailable.")
    for name, value in (("MAX_UPLOAD_BYTES", MAX_UPLOAD_BYTES), ("MAX_PROJECT_FILES", MAX_PROJECT_FILES), ("MAX_BOT_DISK_BYTES", MAX_BOT_DISK_BYTES)):
        if int(value) <= 0:
            raise RuntimeError(f"{name} must be positive.")


# ============================================================
# XX V2 SECURITY / QUALITY / AUDIT LAYER
# ============================================================

SENSITIVE_KEY_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|AUTH|COOKIE|CREDENTIAL)", re.I)
DANGEROUS_CALLS = {
    "eval", "exec", "compile", "__import__", "system", "popen", "spawn", "spawnl",
    "spawnlp", "spawnv", "spawnvp", "fork", "forkpty"
}
DANGEROUS_MODULES = {"ctypes", "pickle", "marshal", "pty", "resource"}


def _audit_redact(value):
    if isinstance(value, dict):
        return {k: ("***REDACTED***" if SENSITIVE_KEY_RE.search(str(k)) else _audit_redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_audit_redact(v) for v in value]
    text = redact_sensitive_text(value, 1200)
    return text


def security_audit_event(action, bot_id=None, owner_id=None, **details):
    record = {
        "id": uuid.uuid4().hex,
        "ts": now_iso(),
        "action": action,
        "bot_id": bot_id,
        "owner_id": owner_id,
        "pid": os.getpid(),
        "details": _audit_redact(details),
    }
    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        logger.exception("Audit log write failed")
    return record


def _file_inventory(bot_dir):
    total = 0
    bytes_total = 0
    hashes = {}
    for root, dirs, files in os.walk(bot_dir):
        dirs[:] = [d for d in dirs if d not in {".venv", "__pycache__", ".git"}]
        for name in files:
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
                total += 1
                bytes_total += size
                if total <= MAX_PROJECT_FILES:
                    digest = hashlib.sha256()
                    with open(path, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            digest.update(chunk)
                    hashes[os.path.relpath(path, bot_dir)] = digest.hexdigest()
            except (OSError, ValueError):
                continue
    return total, bytes_total, hashes


def security_scan_project(bot_dir):
    """Static preflight: detect high-risk Python primitives without executing code."""
    findings = []
    total_files, total_bytes, hashes = _file_inventory(bot_dir)
    if total_files > MAX_PROJECT_FILES:
        findings.append({"severity": "critical", "type": "file_count_limit", "message": f"Project contains {total_files} files; limit is {MAX_PROJECT_FILES}."})
    if total_bytes > MAX_BOT_DISK_BYTES:
        findings.append({"severity": "critical", "type": "project_size_limit", "message": f"Project uses {total_bytes} bytes; limit is {MAX_BOT_DISK_BYTES}."})

    for rel, digest in hashes.items():
        if not rel.endswith(".py"):
            continue
        path = os.path.join(bot_dir, rel)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root in DANGEROUS_MODULES:
                            findings.append({"severity": "high", "type": "dangerous_import", "file": rel, "module": root})
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root = node.module.split(".")[0]
                    if root in DANGEROUS_MODULES:
                        findings.append({"severity": "high", "type": "dangerous_import", "file": rel, "module": root})
                elif isinstance(node, ast.Call):
                    name = None
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    if name in DANGEROUS_CALLS:
                        findings.append({"severity": "high", "type": "dangerous_call", "file": rel, "call": name, "line": getattr(node, "lineno", None)})
        except SyntaxError as exc:
            findings.append({"severity": "critical", "type": "syntax_error", "file": rel, "message": safe_text(exc, 500)})
        except Exception as exc:
            findings.append({"severity": "medium", "type": "scan_error", "file": rel, "message": safe_text(exc, 500)})

    report = {
        "schema": 2,
        "created_at": now_iso(),
        "project_files": total_files,
        "project_bytes": total_bytes,
        "sha256": hashes,
        "findings": findings,
        "risk": "CRITICAL" if any(x["severity"] == "critical" for x in findings) else ("HIGH" if any(x["severity"] == "high" for x in findings) else ("MEDIUM" if findings else "LOW")),
    }
    return report


def write_security_manifest(bot_id, report):
    path = os.path.join(MANIFEST_DIR, f"{bot_id}.json")
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    return path


def _dependency_manifest(bot_dir, runtime_python=None):
    """Create a machine-readable dependency inventory when a runtime exists."""
    runtime_python = runtime_python or sys.executable
    result = {"generated_at": now_iso(), "python": runtime_python, "packages": [], "requirements": []}
    for name in ("requirements.txt", "requirements.lock", "pyproject.toml", "Pipfile.lock", "poetry.lock"):
        if os.path.isfile(os.path.join(bot_dir, name)):
            result["requirements"].append(name)
    try:
        proc = subprocess.run([runtime_python, "-m", "pip", "list", "--format=json"], cwd=bot_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if proc.returncode == 0:
            result["packages"] = json.loads(proc.stdout or "[]")
    except Exception as exc:
        result["error"] = safe_text(exc, 500)
    return result


def _hardened_deployment_preflight(bot_id):
    state = user_deploy_states.get(bot_id, {})
    bot_dir = os.path.abspath(os.path.join(HOST_DIR, bot_id))
    report = security_scan_project(bot_dir)
    write_security_manifest(bot_id, report)
    security_audit_event("deployment_security_scan", bot_id, state.get("owner_id"), risk=report["risk"], findings=len(report["findings"]))
    if report["risk"] == "CRITICAL" or (SECURITY_SCAN_STRICT and report["risk"] == "HIGH"):
        raise RuntimeError("Security preflight blocked deployment. Review the security manifest.")
    return report


# Add a second-generation resource/health snapshot without disturbing the original API.
def build_advanced_runtime_snapshot(bot_id):
    status = get_bot_status(bot_id)
    health = inspect_bot_health(bot_id)
    data = hosted_processes.get(bot_id, {})
    proc = data.get("process")
    children = []
    open_files = None
    threads = None
    if psutil and proc and proc.poll() is None:
        try:
            pp = psutil.Process(proc.pid)
            children = [{"pid": c.pid, "name": c.name()} for c in pp.children(recursive=True)]
            try: open_files = len(pp.open_files())
            except Exception: pass
            try: threads = pp.num_threads()
            except Exception: pass
        except Exception:
            pass
    return {
        "schema": 2,
        "bot_id": bot_id,
        "status": status,
        "health": health,
        "runtime": {"python": data.get("runtime_python"), "isolated_env": bool(data.get("isolated_env")), "children": children, "open_files": open_files, "threads": threads},
        "metrics": ensure_metrics(bot_id),
        "deployment": deployment_runtime.get(bot_id, {}),
        "manifest": os.path.join(MANIFEST_DIR, f"{bot_id}.json"),
    }


@app.route("/api/v2/health")
def advanced_health_api():
    supplied = request.headers.get("X-Health-Key", "")
    if not HEALTH_API_KEY or not hmac.compare_digest(supplied, HEALTH_API_KEY):
        return jsonify({"error": "forbidden"}), 403
    disk = shutil.disk_usage("/")
    return jsonify({
        "schema": 2,
        "status": "ok",
        "engine": {"pid": os.getpid(), "uptime": get_readable_uptime(time.time() - engine_start_time), "workers": len(deployment_workers)},
        "server": {"cpu": psutil.cpu_percent(interval=0.05) if psutil else None, "ram": psutil.virtual_memory()._asdict() if psutil else None, "disk": {"used": disk.used, "free": disk.free, "total": disk.total}},
        "queue": deployment_queue.qsize(),
        "bots": {bid: build_advanced_runtime_snapshot(bid) for bid in list(hosted_processes)[:500]},
    })


@app.route("/api/v2/audit")
def advanced_audit_api():
    supplied = request.headers.get("X-Health-Key", "")
    if not HEALTH_API_KEY or not hmac.compare_digest(supplied, HEALTH_API_KEY):
        return jsonify({"error": "forbidden"}), 403
    events = []
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8", errors="ignore") as fh:
            for line in list(fh)[-200:]:
                try: events.append(json.loads(line))
                except Exception: pass
    except FileNotFoundError:
        pass
    return jsonify({"schema": 2, "events": events})


security_audit_event("engine_module_loaded", details="XX V2 hardening layer active")


# ============================================================
# FINAL ULTRA PROMAX SELF-AUDIT
# ============================================================

def engine_capabilities():
    """Expose capability state without claiming unexecuted isolation/tests."""
    return {
        "process_tree_management": True,
        "venv_isolation": bool(ISOLATED_BOT_ENVS),
        "container_runtime_detected": shutil.which("docker") is not None,
        "true_container_sandbox_verified": SANDBOX_MODE in {"docker", "required"} and _docker_available(),
        "kernel_hard_limits": SANDBOX_MODE in {"docker", "required"} and _docker_available(),
        "deployment_queue_bounded": True,
        "deployment_queue_capacity": DEPLOYMENT_QUEUE_MAX_ITEMS,
        "external_runtime_tests": "NOT EXECUTED",
    }

def run_engine_self_audit():
    """
    Lightweight source/runtime readiness audit.
    This does not claim that external infrastructure tests passed.
    It validates local invariants that can be proven from the running
    process: registry integrity, bot record shape, deployment telemetry
    freshness, and duplicate-process identity.
    """
    findings = []
    checked = 0

    try:
        with registry_lock:
            for bot_id, record in list(hosted_processes.items()):
                checked += 1
                if not isinstance(record, dict):
                    findings.append(f"{bot_id}: invalid process record")
                    continue
                pid = record.get("pid")
                if pid is not None and not isinstance(pid, int):
                    findings.append(f"{bot_id}: invalid PID type")
                owner = record.get("owner_id")
                if owner is None:
                    findings.append(f"{bot_id}: missing owner_id")

        now = time.time()
        with deployment_runtime_lock:
            for bot_id, runtime in list(deployment_runtime.items()):
                checked += 1
                if not isinstance(runtime, dict):
                    findings.append(f"{bot_id}: invalid deployment runtime")
                    continue
                ts = runtime.get("updated_at")
                if ts is not None:
                    try:
                        age = max(0.0, now - float(ts))
                        if age > TELEMETRY_STALE_AFTER:
                            runtime["freshness"] = "STALE"
                    except (TypeError, ValueError):
                        findings.append(f"{bot_id}: invalid telemetry timestamp")

        return {
            "ok": not findings,
            "checked": checked,
            "findings": findings,
            "timestamp": now_iso(),
        }
    except Exception as exc:
        logger.exception("Self-audit failed.")
        return {
            "ok": False,
            "checked": checked,
            "findings": [f"self-audit exception: {type(exc).__name__}"],
            "timestamp": now_iso(),
        }


# ============================================================
# DEEP-HIDDEN STATIC VERIFICATION ENGINE
# ============================================================

DEEP_AUDIT_VERSION = 1
DEEP_AUDIT_MAX_SOURCE_BYTES = int(os.environ.get("DEEP_AUDIT_MAX_SOURCE_BYTES", str(25 * 1024 * 1024)))
DEEP_AUDIT_REPORT_FILE = os.environ.get("DEEP_AUDIT_REPORT_FILE", os.path.join(BASE_DIR, "deep_audit_report.json"))


def _audit_source_text(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValidationError(f"Audit source does not exist: {path}")
    if path.stat().st_size > DEEP_AUDIT_MAX_SOURCE_BYTES:
        raise ResourceLimitError("Audit source exceeds DEEP_AUDIT_MAX_SOURCE_BYTES.")
    return path, path.read_text(encoding="utf-8", errors="replace")


def _ast_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _ast_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _deep_static_audit(source_path=None):
    """
    Deep static verification for features that cannot be fully executed here.

    This intentionally reports evidence classes separately. It never converts
    source inspection into runtime verification.
    """
    source_path = source_path or os.path.abspath(__file__)
    path, source = _audit_source_text(source_path)
    tree = ast.parse(source, filename=str(path))

    functions = {}
    classes = {}
    imports = set()
    callbacks = []
    routes = []
    call_edges = []
    dangerous = []
    resource_ops = []
    exception_sites = []
    locks = []
    subprocess_sites = []
    filesystem_sites = []
    network_sites = []
    state_literals = set()
    TODO_RE = re.compile(r"(?i)\\b(?:TODO|FIXME)\\b|placeholder|dummy|mock|fake")
    text_hits = []

    for lineno, line in enumerate(source.splitlines(), 1):
        if lineno >= 6550 and lineno <= 6810:
            continue
        if TODO_RE.search(line):
            text_hits.append({"line": lineno, "text": safe_text(line.strip(), 240)})

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = {
                "line": node.lineno,
                "async": isinstance(node, ast.AsyncFunctionDef),
                "args": [a.arg for a in node.args.args],
            }
            for deco in node.decorator_list:
                dname = _ast_name(deco)
                if dname and ("message_handler" in dname or "callback_query_handler" in dname):
                    callbacks.append({"name": node.name, "line": node.lineno, "decorator": dname})
                if dname == "app.route":
                    routes.append({"handler": node.name, "line": node.lineno, "route": ast.unparse(deco)})
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = _ast_name(child.func)
                    if callee:
                        call_edges.append({"caller": node.name, "callee": callee, "line": getattr(child, "lineno", node.lineno)})
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = node.lineno
        elif isinstance(node, ast.Import):
            imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            name = _ast_name(node.func) or ""
            short = name.rsplit(".", 1)[-1]
            if short in DANGEROUS_CALLS or name in {"os.system", "os.popen", "subprocess.Popen", "subprocess.run", "subprocess.call"}:
                if name not in {"re.compile", "py_compile.compile"}:
                    dangerous.append({"line": getattr(node, "lineno", None), "call": name})
            if short in {"Popen", "run", "call", "check_call", "check_output"} or name.startswith("subprocess."):
                subprocess_sites.append({"line": getattr(node, "lineno", None), "call": name})
            if short in {"open", "remove", "unlink", "rmtree", "replace", "makedirs", "mkdir", "copy2", "move"} or name.startswith(("os.", "shutil.", "pathlib.")):
                filesystem_sites.append({"line": getattr(node, "lineno", None), "call": name})
            if short in {"get", "post", "request", "send_message", "send_document", "set_webhook", "remove_webhook"} or name.startswith(("requests.", "socket.")):
                network_sites.append({"line": getattr(node, "lineno", None), "call": name})
            if short in {"Lock", "RLock", "flock", "acquire"} or name.endswith(".acquire"):
                locks.append({"line": getattr(node, "lineno", None), "call": name})
            if short in {"Queue", "put", "get", "task_done", "join"} or name.startswith("queue."):
                resource_ops.append({"line": getattr(node, "lineno", None), "call": name})
        elif isinstance(node, (ast.Try,)):
            exception_sites.append({"line": getattr(node, "lineno", None), "handlers": len(node.handlers), "has_finally": bool(node.finalbody)})
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value.strip().upper()
            if val in {"RUNNING", "STOPPED", "STARTING", "STOPPING", "DEPLOYING", "INSTALLING", "RECOVERING", "HEALTHY", "UNHEALTHY", "FAILED", "WARNING", "CRITICAL", "LIMITED", "NORMAL"}:
                state_literals.add(val)

    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    defined = set(functions) | set(classes)
    unresolved_local_calls = []
    for edge in call_edges:
        callee = edge["callee"]
        root = callee.split(".")[0]
        if "." not in callee and root not in defined and root not in names:
            unresolved_local_calls.append(edge)

    callback_names = {x["name"] for x in callbacks}
    callback_refs = set()
    for line in source.splitlines():
        m = re.search(r"callback_data\\s*=\\s*[\"']([^\"']+)", line)
        if m:
            callback_refs.add(m.group(1))

    endpoint_auth = {}
    lines = source.splitlines()
    for route in routes:
        start = route["line"] - 1
        block = "\n".join(lines[start:min(len(lines), start + 35)])
        endpoint_auth[route["handler"]] = {
            "has_health_key": "X-Health-Key" in block,
            "has_admin_check": "is_admin" in block,
            "has_auth_check": "Authorization" in block or "authenticate" in block.lower(),
        }

    findings = []
    def finding(severity, category, message, evidence=None):
        item = {"severity": severity, "category": category, "message": message}
        if evidence is not None:
            item["evidence"] = evidence
        findings.append(item)

    if text_hits:
        finding("medium", "completion_markers", "Source contains TODO/FIXME/placeholder-like markers; each occurrence requires disposition.", text_hits[:50])
    if unresolved_local_calls:
        finding("medium", "call_graph", "Potential unresolved local call targets were found; dynamic names can create false positives and require review.", unresolved_local_calls[:100])
    if dangerous:
        finding("high", "dangerous_primitives", "Dangerous process/evaluation primitives exist in the engine source; inspect each use and sandbox boundary.", dangerous[:100])
    if "health_detailed" in endpoint_auth and not endpoint_auth["health_detailed"]["has_health_key"]:
        finding("high", "api_auth", "Detailed health endpoint lacks a health-key check.")
    if "deployments_status" in endpoint_auth and not endpoint_auth["deployments_status"]["has_health_key"]:
        finding("high", "api_auth", "Deployment telemetry endpoint lacks a health-key check.")
    if not locks:
        finding("medium", "concurrency", "No lock/acquire operations were discovered; shared mutable state should be reviewed.")
    if not exception_sites:
        finding("medium", "error_flow", "No try/except blocks discovered; error propagation should be reviewed.")

    # State transition sanity: reject obviously contradictory direct state assignments.
    invalid_direct_states = []
    for m in re.finditer(r"status\s*=\s*[\"']([A-Z_]+)[\"']", source):
        st = m.group(1)
        if st not in state_literals:
            invalid_direct_states.append(st)
    if invalid_direct_states:
        finding("low", "state_machine", "Status literals were assigned that are outside the discovered state vocabulary.", sorted(set(invalid_direct_states)))

    report = {
        "schema": "XX-DEEP-AUDIT-1",
        "audit_version": DEEP_AUDIT_VERSION,
        "created_at": now_iso(),
        "source": str(path),
        "classification": "STATICALLY VERIFIED — RUNTIME UNVERIFIED",
        "source_bytes": path.stat().st_size,
        "inventory": {
            "functions": functions,
            "classes": classes,
            "imports": sorted(imports),
            "callbacks": callbacks,
            "routes": routes,
            "call_edges": len(call_edges),
            "subprocess_sites": subprocess_sites,
            "filesystem_sites": filesystem_sites,
            "network_sites": network_sites,
            "lock_sites": locks,
            "exception_sites": exception_sites,
            "states": sorted(state_literals),
            "callback_data_literals": sorted(callback_refs),
        },
        "verification": {
            "source_parse": "PASS",
            "data_flow": "STATIC REVIEW",
            "control_flow": "STATIC REVIEW",
            "state_flow": "STATIC REVIEW",
            "call_graph": "STATIC REVIEW",
            "dependency_flow": "STATIC REVIEW",
            "error_flow": "STATIC REVIEW",
            "resource_flow": "STATIC REVIEW",
            "security": "STATIC REVIEW",
            "concurrency": "STATIC REVIEW",
            "restart": "STATIC REVIEW",
            "long_run": "STATIC REVIEW",
            "runtime": "NOT EXECUTED",
        },
        "findings": findings,
        "counts": {
            "critical": sum(x["severity"] == "critical" for x in findings),
            "high": sum(x["severity"] == "high" for x in findings),
            "medium": sum(x["severity"] == "medium" for x in findings),
            "low": sum(x["severity"] == "low" for x in findings),
        },
    }
    return report


def run_deep_static_audit(source_path=None, persist=True):
    report = _deep_static_audit(source_path)
    if persist:
        temp = DEEP_AUDIT_REPORT_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, DEEP_AUDIT_REPORT_FILE)
    security_audit_event("deep_static_audit_completed", findings=report["counts"], classification=report["classification"])
    return report


@app.route("/api/v3/deep-audit")
def deep_audit_api():
    supplied = request.headers.get("X-Health-Key", "")
    if not HEALTH_API_KEY or not hmac.compare_digest(supplied, HEALTH_API_KEY):
        return jsonify({"error": "forbidden"}), 403
    try:
        return jsonify(run_deep_static_audit(persist=True))
    except Exception as exc:
        logger.exception("Deep static audit failed.")
        return jsonify({"error": "audit_failed", "type": type(exc).__name__}), 500

# ============================================================
# MAIN RUNNER
# ============================================================



# ============================================================================
# XX HOSTING ENGINE — ULTRA PROMAX HARDENING LAYER
# ============================================================================

class EngineError(Exception):
    pass

class ValidationError(EngineError):
    pass

class AuthorizationError(EngineError):
    pass

class ResourceLimitError(EngineError):
    pass

class DeploymentError(EngineError):
    pass

class RecoveryError(EngineError):
    pass

class SecurityError(EngineError):
    pass

@dataclass
class TelemetryValue:
    value: object = None
    source: str = "unknown"
    timestamp: float = 0.0
    valid: bool = False

    @property
    def age(self):
        return max(0.0, time.time() - self.timestamp) if self.timestamp else None

    @property
    def freshness(self):
        if not self.valid or not self.timestamp:
            return "UNKNOWN"
        return "STALE" if self.age > 10 else "FRESH"

    def display(self, unknown="UNKNOWN"):
        return str(self.value) if self.valid else unknown

@dataclass
class Diagnostic:
    error_id: str
    correlation_id: str
    category: str
    message: str
    cause: str = "Unknown"
    action: str = "No automatic action"
    next_action: str = "Inspect diagnostics"
    recoverable: bool = False
    timestamp: float = field(default_factory=time.time)

    def safe_dict(self):
        return {
            "error_id": self.error_id,
            "correlation_id": self.correlation_id,
            "category": self.category,
            "message": self.message,
            "cause": self.cause,
            "action": self.action,
            "next_action": self.next_action,
            "recoverable": self.recoverable,
            "timestamp": self.timestamp,
        }

class IdempotencyGuard:
    def __init__(self, max_items=4096, ttl=3600):
        self.max_items, self.ttl = max_items, ttl
        self._lock = threading.RLock()
        self._items = collections.OrderedDict()

    def acquire(self, key):
        now = time.time()
        with self._lock:
            for k, ts in list(self._items.items()):
                if now - ts > self.ttl:
                    self._items.pop(k, None)
            if key in self._items:
                return False
            self._items[key] = now
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
            return True

    def release(self, key):
        with self._lock:
            self._items.pop(key, None)

class AdaptiveTelemetry:
    def __init__(self, normal_interval=1.5):
        self.normal_interval = max(0.25, float(normal_interval))
        self._lock = threading.RLock()
        self._last_emit = 0.0

    def should_emit(self, critical=False):
        now = time.time()
        with self._lock:
            if critical or now - self._last_emit >= self.normal_interval:
                self._last_emit = now
                return True
            return False

def fresh_metric(value, source, valid=True):
    return TelemetryValue(value, source, time.time(), bool(valid))

def new_diagnostic(category, message, cause="Unknown",
                   action="No automatic action",
                   next_action="Inspect diagnostics", recoverable=False):
    return Diagnostic(
        secrets.token_hex(8), secrets.token_hex(8), category, message,
        cause, action, next_action, recoverable
    )

def validate_project_limits(root, max_files=None, max_bytes=None):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValidationError("Project directory does not exist.")
    count = total = 0
    for p in root.rglob("*"):
        if p.is_symlink():
            continue
        try:
            if p.is_file():
                count += 1
                total += p.stat().st_size
                if max_files is not None and count > max_files:
                    raise ResourceLimitError("Project file-count limit exceeded.")
                if max_bytes is not None and total > max_bytes:
                    raise ResourceLimitError("Project size limit exceeded.")
        except FileNotFoundError:
            continue
    return {"files": count, "bytes": total}

def validate_zip_archive(path, max_compressed_bytes, max_uncompressed_bytes,
                         max_files, max_ratio=100.0):
    path = Path(path)
    if path.stat().st_size > max_compressed_bytes:
        raise ResourceLimitError("Compressed ZIP size limit exceeded.")
    total = count = 0
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            count += 1
            if count > max_files:
                raise ResourceLimitError("ZIP file-count limit exceeded.")
            name = info.filename.replace("\\", "/")
            parts = [x for x in name.split("/") if x not in ("", ".")]
            if name.startswith("/") or ".." in parts:
                raise SecurityError("ZIP path traversal detected.")
            total += max(0, int(info.file_size))
            if total > max_uncompressed_bytes:
                raise ResourceLimitError("ZIP extraction quota exceeded.")
            ratio = float(info.file_size) / max(1, int(info.compress_size))
            if info.file_size and ratio > max_ratio:
                raise SecurityError("ZIP compression-ratio limit exceeded.")
    return {
        "files": count,
        "compressed_bytes": path.stat().st_size,
        "uncompressed_bytes": total,
    }

def verify_python_tree(root):
    root = Path(root)
    failures = []
    for p in root.rglob("*.py"):
        if p.is_symlink():
            continue
        try:
            compile(p.read_bytes(), str(p), "exec", dont_inherit=True)
        except Exception as exc:
            failures.append({"file": str(p), "error": str(exc)})
    if failures:
        raise ValidationError(f"Python compilation failed for {len(failures)} file(s).")
    return True

def safe_stream_copy(src, dst, chunk_size=1024*1024, max_bytes=None):
    copied = 0
    with open(src, "rb") as rf, open(dst, "wb") as wf:
        while True:
            chunk = rf.read(chunk_size)
            if not chunk:
                break
            copied += len(chunk)
            if max_bytes is not None and copied > max_bytes:
                raise ResourceLimitError("Streaming copy limit exceeded.")
            wf.write(chunk)
    return copied

def atomic_directory_activate(staging, active):
    staging, active = Path(staging).resolve(), Path(active).resolve()
    if not staging.is_dir():
        raise DeploymentError("Staging directory is missing.")
    active.parent.mkdir(parents=True, exist_ok=True)
    previous = active.with_name(active.name + ".previous")
    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)
    if active.exists():
        os.replace(str(active), str(previous))
    try:
        os.replace(str(staging), str(active))
    except Exception:
        if previous.exists() and not active.exists():
            os.replace(str(previous), str(active))
        raise
    return previous

def resource_state(value, notice, warning, critical, limit):
    try:
        x = float(value)
    except Exception:
        return "UNKNOWN"
    if x >= limit: return "LIMIT"
    if x >= critical: return "CRITICAL"
    if x >= warning: return "WARNING"
    if x >= notice: return "NOTICE"
    return "NORMAL"

def classify_failure(exc):
    msg = str(exc).lower()
    if "no module named" in msg: return "MISSING_DEPENDENCY"
    if "timeout" in msg: return "TIMEOUT"
    if "permission denied" in msg: return "PERMISSION"
    if "no space left" in msg: return "DISK"
    if "memory" in msg: return "MEMORY"
    if "connection" in msg or "network" in msg: return "NETWORK"
    if "syntax" in msg: return "SYNTAX"
    return "UNKNOWN"

def make_safe_failure(exc, action="No automatic action",
                      next_action="Inspect the error details"):
    category = classify_failure(exc)
    recoverable = category in {"MISSING_DEPENDENCY", "TIMEOUT", "NETWORK", "DISK"}
    return new_diagnostic(
        category, f"Operation failed: {type(exc).__name__}", str(exc)[:500],
        action, next_action, recoverable
    )

class HealthVerifier:
    @staticmethod
    def verify_process(proc):
        if proc is None:
            return False, "No process object."
        try:
            if proc.poll() is not None:
                return False, f"Process exited with code {proc.returncode}."
            return True, "Process is alive."
        except Exception as exc:
            return False, f"Unable to verify process: {type(exc).__name__}"

    @staticmethod
    def verify_callable(check):
        try:
            return bool(check()), "Application health probe completed."
        except Exception as exc:
            return False, f"Application health probe failed: {type(exc).__name__}"

ENGINE_IDEMPOTENCY = IdempotencyGuard()
ENGINE_TELEMETRY = AdaptiveTelemetry()


if __name__ == "__main__":

    validate_environment()

    acquire_engine_lock()

    signal.signal(
        signal.SIGINT,
        signal_handler,
    )

    signal.signal(
        signal.SIGTERM,
        signal_handler,
    )

    try:

        load_registry()

        try:
            audit_report = run_deep_static_audit(persist=True)
            logger.info(
                "Deep static audit: %s | findings=%s",
                audit_report["classification"],
                audit_report["counts"],
            )
        except Exception:
            logger.exception("Deep static audit could not be completed at startup.")

        start_deployment_workers()

        threading.Thread(
            target=auto_healing_monitor,
            name="health-watchdog",
            daemon=True,
        ).start()

        threading.Thread(
            target=registry_flush_worker,
            name="registry-flusher",
            daemon=True,
        ).start()

        transport = configure_telegram_transport()

        if transport == "polling":
            start_local_polling_once()

        logger.info(
            "XX Supercharged Hosting Engine started."
        )

        logger.info(
            "Single-instance protection: ACTIVE"
        )

        logger.info(
            "Duplicate bot protection: ACTIVE"
        )

        logger.info(
            "Health watchdog: ACTIVE"
        )

        logger.info(
            "Atomic registry: ACTIVE"
        )

        logger.info(
            "Deployment queue: ACTIVE"
        )

        logger.info(
            "Version / rollback system: ACTIVE"
        )

        app.run(
            host="0.0.0.0",
            port=PORT,
            threaded=True,
        )

    except KeyboardInterrupt:

        logger.info(
            "Keyboard interrupt received."
        )

    except Exception:

        logger.exception(
            "Fatal engine exception."
        )

    finally:

        try:
            if IS_RENDER:
                bot.remove_webhook()
                logger.info(
                    "Telegram webhook removed during shutdown."
                )
        except Exception:
            logger.exception(
                "Failed to remove Telegram webhook during shutdown."
            )

        cleanup_engine()
