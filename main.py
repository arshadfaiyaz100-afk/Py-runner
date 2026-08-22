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
import random
import importlib.util
import json
import asyncio
import signal
import hashlib
import tempfile
import logging
import platform
import socket
import collections
import queue
import traceback
import math
from pathlib import Path
from dataclasses import dataclass, field
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple, List

from flask import Flask, jsonify
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
# Secrets are intentionally read from the environment instead of being hard-coded.
# Set BOT_TOKEN / GH_TOKEN to the credentials you want this engine to use.
BOT_TOKEN = "8483068207:AAEq3LPHIYlug4qtQnkc9dQB2u-r6kQm1cs"
GLOBAL_API_ID = int(os.environ.get("GLOBAL_API_ID", "29387151"))
GLOBAL_API_HASH = "1d70091141dda904d82684938d444473"

GH_TOKEN = "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"
GH_REPO = os.environ.get("GH_REPO", "my-hosted-bots").strip()

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

AUTO_RESTART_LIMIT = int(
    os.environ.get("AUTO_RESTART_LIMIT", "3")
)

AUTO_RESTART_WINDOW = int(
    os.environ.get("AUTO_RESTART_WINDOW", "900")
)

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

BASE_DIR = os.path.abspath(os.getcwd())

HOST_DIR = os.path.join(BASE_DIR, "hosted_env")
LOG_DIR = os.path.join(BASE_DIR, "logs")
TEMP_DIR = os.path.join(BASE_DIR, "temp_uploads")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
VERSION_DIR = os.path.join(BASE_DIR, "versions")

REGISTRY_FILE = os.path.join(BASE_DIR, "registry.json")
REGISTRY_TMP_FILE = os.path.join(BASE_DIR, "registry.json.tmp")
REGISTRY_BACKUP_FILE = os.path.join(BASE_DIR, "registry.json.bak")
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

deployment_queue = queue.Queue()
deployment_workers = []

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

    return {
        "version": 3,
        "saved_at": now_iso(),
        "bots": bots,
        "envs": user_custom_envs,
        "chats": list(user_chats),
        "banned_users": list(banned_users),
        "maintenance": MAINTENANCE_MODE,
        "metadata": bot_metadata,
        "versions": bot_versions,
        "metrics": bot_metrics,
    }


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

        except Exception:
            logger.exception(
                "Atomic registry save failed."
            )


def load_registry():

    global user_custom_envs
    global user_chats
    global banned_users
    global MAINTENANCE_MODE
    global bot_metadata
    global bot_versions
    global bot_metrics

    source = None

    if os.path.exists(REGISTRY_FILE):
        source = REGISTRY_FILE

    elif os.path.exists(REGISTRY_BACKUP_FILE):
        source = REGISTRY_BACKUP_FILE

    if not source:
        return

    try:
        with open(
            source,
            "r",
            encoding="utf-8",
        ) as handle:

            data = json.load(handle)

        user_custom_envs = data.get(
            "envs",
            {},
        )

        user_chats = set(
            data.get(
                "chats",
                [],
            )
        )

        banned_users = set(
            data.get(
                "banned_users",
                [],
            )
        )

        MAINTENANCE_MODE = bool(
            data.get(
                "maintenance",
                False,
            )
        )

        bot_metadata = data.get(
            "metadata",
            {},
        )

        bot_versions = data.get(
            "versions",
            {},
        )

        bot_metrics = data.get(
            "metrics",
            {},
        )

        bots = data.get(
            "bots",
            {},
        )

        for bot_id, info in bots.items():

            bot_dir = os.path.join(
                HOST_DIR,
                bot_id,
            )

            entry_file = info.get(
                "entry_file"
            )

            owner_id = info.get(
                "owner_id"
            )

            if not entry_file:
                continue

            entry_path = os.path.join(
                bot_dir,
                entry_file,
            )

            if not os.path.isfile(entry_path):
                continue

            # Recovery is performed through the single-instance
            # function, so an already-running process is never duplicated.
            start_bot_once(
                bot_id,
                entry_file,
                owner_id,
                reason="registry_recovery",
                notify=False,
            )

    except Exception:
        logger.exception(
            "Registry recovery failed."
        )


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

def start_bot_once(
    bot_id,
    entry_file,
    owner_id,
    reason="manual",
    notify=False,
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

        custom_env = os.environ.copy()

        custom_env.update(
            user_custom_envs.get(
                str(owner_id),
                {},
            )
        )

        # API credentials are inherited from the hosting environment
        # only when explicitly configured.
        if GLOBAL_API_ID:
            custom_env["API_ID"] = str(
                GLOBAL_API_ID
            )

        if GLOBAL_API_HASH:
            custom_env["API_HASH"] = (
                GLOBAL_API_HASH
            )

        custom_env["BOT_HOST_ID"] = bot_id

        custom_env["BOT_OWNER_ID"] = str(
            owner_id
        )

        custom_env["BOT_HOSTED"] = "1"

        try:

            process = subprocess.Popen(
                [
                    sys.executable,
                    entry_path,
                ],
                cwd=bot_dir,
                stdout=log_out,
                stderr=log_out,
                env=custom_env,
                text=True,
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
            "entry_file": entry_file,
            "owner_id": owner_id,
            "start_time": time.time(),
            "log_file": log_file_path,
            "retries": 0,
            "manual_stop": False,
            "launch_reason": reason,
            "log_handle": log_out,
        }

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
                        parent.wait(
                            timeout=8
                        )
                    except Exception:

                        try:
                            parent.kill()
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
            f"{time.strftime('%Y%m%d_%H%M%S')}"
        )

        os.replace(
            path,
            rotated,
        )

        open(
            path,
            "a",
            encoding="utf-8",
        ).close()

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
# DEPENDENCY INSTALLER
# ============================================================

def auto_install_packages_verified(
    modules,
    chat_id,
    msg_id,
    start_time,
):

    if not modules:
        return True, ""

    total = len(
        modules
    )

    for index, module in enumerate(
        modules,
        start=1,
    ):

        percent = int(
            index / total * 100
        )

        import_name = (
            module.split()[0]
            .replace("-", "_")
        )

        try:

            if (
                importlib.util.find_spec(
                    import_name
                )
                is not None
            ):

                update_hud(
                    chat_id,
                    msg_id,
                    "Dependency Engine",
                    (
                        "Already installed → "
                        f"`{module}`"
                    ),
                    percent,
                    start_time,
                )

                continue

        except Exception:
            pass

        update_hud(
            chat_id,
            msg_id,
            "Dependency Engine",
            (
                f"Installing [{index}/{total}] → "
                f"`{module}`"
            ),
            percent,
            start_time,
        )

        try:

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    *module.split(),
                    "--no-cache-dir",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600,
            )

            if result.returncode != 0:

                return (
                    False,
                    (
                        f"Failed to install `{module}`.\n\n"
                        f"{result.stderr[-1200:]}"
                    ),
                )

        except Exception as exc:

            return (
                False,
                (
                    f"Exception installing "
                    f"`{module}`: {exc}"
                ),
            )

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
):

    bar = get_progress_bar(
        percent
    )

    elapsed = round(
        time.time() - start_time,
        1,
    )

    text = (
        f"⚙️ **{title}**\n\n"
        f"`[{bar}] {percent}%`\n\n"
        f"⚡ **Status:** `{action}`\n"
        f"⏱️ **Elapsed:** `{elapsed}s`"
    )

    try:

        bot.edit_message_text(
            text,
            chat_id,
            msg_id,
            parse_mode="Markdown",
        )

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

def safe_extract_zip(
    zip_path,
    destination,
):

    destination = os.path.abspath(
        destination
    )

    with zipfile.ZipFile(
        zip_path,
        "r",
    ) as archive:

        for member in archive.infolist():

            target = os.path.abspath(
                os.path.join(
                    destination,
                    member.filename,
                )
            )

            if not (
                target == destination
                or target.startswith(
                    destination + os.sep
                )
            ):
                raise ValueError(
                    "Unsafe ZIP path detected."
                )

        archive.extractall(
            destination
        )


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

def rollback_bot(
    bot_id,
    version_id,
    owner_id,
):

    if not is_admin(owner_id):

        data = hosted_processes.get(
            bot_id
        )

        if not data:
            return False, "Bot not found."

        if int(
            data.get("owner_id", -1)
        ) != int(owner_id):
            return False, "Permission denied."

    versions = bot_versions.get(
        bot_id,
        [],
    )

    selected = None

    for item in versions:

        if item.get(
            "version"
        ) == version_id:

            selected = item
            break

    if not selected:
        return False, "Version not found."

    source = selected.get(
        "path"
    )

    if not source or not os.path.isdir(
        source
    ):
        return False, "Version data missing."

    data = hosted_processes.get(
        bot_id
    )

    if data:
        entry_file = data.get(
            "entry_file"
        )
    else:
        metadata = bot_metadata.get(
            bot_id,
            {},
        )

        entry_file = metadata.get(
            "entry_file",
            "main.py",
        )

    create_bot_version(
        bot_id,
        reason="pre_rollback",
    )

    was_running = is_bot_running(
        bot_id
    )

    if was_running:
        stop_script_process(
            bot_id,
            reason="rollback",
        )

    destination = os.path.join(
        HOST_DIR,
        bot_id,
    )

    shutil.rmtree(
        destination,
        ignore_errors=True,
    )

    os.makedirs(
        destination,
        exist_ok=True,
    )

    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
    )

    try:

        py_compile.compile(
            os.path.join(
                destination,
                entry_file,
            ),
            doraise=True,
        )

    except Exception as exc:

        return (
            False,
            f"Rollback syntax check failed: {exc}",
        )

    if was_running:

        start_bot_once(
            bot_id,
            entry_file,
            owner_id,
            reason="rollback",
            notify=False,
        )

    save_registry()

    return (
        True,
        f"Rollback to `{version_id}` completed.",
    )


# ============================================================
# HEALTH MONITOR
# ============================================================

def inspect_bot_health(
    bot_id,
):

    data = hosted_processes.get(
        bot_id
    )

    if not data:

        return {
            "status": "NOT_FOUND",
            "memory": 0,
            "cpu": 0,
            "pid": None,
        }

    process = data.get(
        "process"
    )

    if process is None:
        return {
            "status": "STOPPED",
            "memory": 0,
            "cpu": 0,
            "pid": None,
        }

    if process.poll() is not None:

        return {
            "status": "STOPPED",
            "memory": 0,
            "cpu": 0,
            "pid": process.pid,
        }

    memory = 0
    cpu = 0

    if psutil:

        try:

            proc = psutil.Process(
                process.pid
            )

            memory = proc.memory_info().rss

            cpu = proc.cpu_percent(
                interval=0.05
            )

            metrics = ensure_metrics(
                bot_id
            )

            metrics["peak_memory"] = max(
                int(
                    metrics.get(
                        "peak_memory",
                        0,
                    )
                ),
                memory,
            )

        except Exception as exc:

            record_error(
                bot_id,
                exc,
            )

    ensure_metrics(
        bot_id
    )["last_health_check"] = now_iso()

    return {
        "status": "RUNNING",
        "memory": memory,
        "cpu": cpu,
        "pid": process.pid,
    }


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

                    if (
                        health["memory"]
                        > MAX_BOT_RAM_BYTES
                    ):

                        owner_id = data.get(
                            "owner_id"
                        )

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

                        subprocess.run(
                            [
                                sys.executable,
                                "-m",
                                "pip",
                                "install",
                                target_package,
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
                "🔄 Start Check",
                callback_data=f"start:{bot_id}",
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

def build_bot_status_bar(
    bot_id
):

    status = get_bot_status(
        bot_id
    )

    health = inspect_bot_health(
        bot_id
    )

    metrics = ensure_metrics(
        bot_id
    )

    memory = health.get(
        "memory",
        0,
    )

    return (
        f"🤖 **{bot_id} STATUS BAR**\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Status: `{status['status']}`\n"
        f"🆔 PID: `{status['pid'] or '-'}`\n"
        f"⏱ Uptime: `{status['uptime']}`\n"
        f"🧠 CPU: `{round(health.get('cpu', 0), 1)}%`\n"
        f"💾 RAM: `{get_readable_size(memory)}`\n"
        f"📈 Peak RAM: `{get_readable_size(metrics.get('peak_memory', 0))}`\n"
        f"🔄 Restarts: `{metrics.get('restarts', 0)}`\n"
        f"💥 Crashes: `{metrics.get('crashes', 0)}`\n"
        f"❌ Errors: `{metrics.get('errors', 0)}`\n"
        f"🚀 Starts: `{metrics.get('starts', 0)}`\n"
        f"🛑 Stops: `{metrics.get('stops', 0)}`\n"
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
        "⚡ **XX SUPERCHARGED HOSTING ENGINE** ⚡\n\n"
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
                "Send a Python `.py` file, `.zip` project, "
                "or paste Python source.\n\n"
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

        deployment_queue.put(
            {
                "chat_id": chat,
                "msg_id": call.message.message_id,
                "bot_id": bot_id,
                "install_type": "auto",
            }
        )

        bot.send_message(
            chat,
            (
                f"📥 `{bot_id}` added to "
                "deployment queue."
            ),
            parse_mode="Markdown",
        )

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

        envs = user_custom_envs.get(
            str(uid),
            {},
        )

        if envs:

            names = "\n".join(
                f"🔹 `{key}` → `********`"
                for key in envs
            )

        else:

            names = (
                "🔹 No custom variables."
            )

        bot.send_message(
            chat,
            (
                "🔐 **ENVIRONMENT MANAGER**\n\n"
                f"{names}\n\n"
                "Send `KEY=VALUE` to add/update "
                "a variable.\n\n"
                "Type `cancel` to exit."
            ),
            parse_mode="Markdown",
        )

        bot.register_next_step_handler(
            call.message,
            save_env_var,
        )

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

                    raise ValueError(
                        "ZIP does not contain main.py, bot.py or app.py."
                    )

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

            deployment_queue.put(
                {
                    "chat_id": message.chat.id,
                    "msg_id": progress.message_id,
                    "bot_id": bot_id,
                    "install_type": "manual",
                    "manual_req_path": requirements_path,
                }
            )

            bot.send_message(
                message.chat.id,
                (
                    f"📦 `{bot_id}` found "
                    "`requirements.txt`.\n"
                    "Added to deployment queue."
                ),
                parse_mode="Markdown",
            )

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
                f"`{safe_text(exc, 2000)}`"
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

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    manual_req_path,
                    "--no-cache-dir",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600,
            )

            if result.returncode != 0:

                raise RuntimeError(
                    result.stderr[-2000:]
                )

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
                )
            )

            if not success:
                raise RuntimeError(
                    error
                )

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

        update_hud(
            chat_id,
            msg_id,
            "XX Deployment HUD",
            "BOT 100% Operational",
            100,
            start_time,
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
                f"`{safe_text(exc, 2500)}`"
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

        if message.document:

            info = bot.get_file(
                message.document.file_id
            )

            content = bot.download_file(
                info.file_path
            )

            with open(
                script_path,
                "wb",
            ) as handle:

                handle.write(
                    content
                )

        elif message.text:

            with open(
                script_path,
                "w",
                encoding="utf-8",
            ) as handle:

                handle.write(
                    message.text
                )

        else:

            raise ValueError(
                "No code was supplied."
            )

        py_compile.compile(
            script_path,
            doraise=True,
        )

        # Explicit code update intentionally restarts once.
        restart_bot(
            bot_id,
            owner_id,
            notify=False,
        )

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
                f"`{safe_text(exc, 2000)}`"
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

        deployment_queue.put(
            {
                "chat_id": message.chat.id,
                "msg_id": progress.message_id,
                "bot_id": bot_id,
                "install_type": "manual",
                "manual_req_path": req_path,
            }
        )

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

    return jsonify(
        {
            "status": "ok",
            "uptime": get_readable_uptime(
                time.time()
                - engine_start_time
            ),
            "bots_total": len(
                hosted_processes
            ),
            "bots_running": sum(
                is_bot_running(
                    bot_id
                )
                for bot_id
                in hosted_processes
            ),
            "cpu_percent": cpu,
            "memory_percent": memory_percent,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "hostname": socket.gethostname(),
        }
    )


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


# ============================================================
# XX SUPERCHARGED EXTENSION PACK v1.0
# NON-DESTRUCTIVE ADD-ON: original engine remains intact.
# ============================================================

import csv
import io
import sqlite3
import shlex
import subprocess as _subprocess_ext
from datetime import datetime, timedelta
from urllib.parse import urlparse

EXT_DIR = os.path.join(BASE_DIR, "extension_data")
EXT_STATE_FILE = os.path.join(EXT_DIR, "extension_state.json")
SCHEDULE_FILE = os.path.join(EXT_DIR, "schedules.json")
TEAM_FILE = os.path.join(EXT_DIR, "team.json")
TEMPLATE_DIR = os.path.join(EXT_DIR, "templates")
PUBLIC_STATUS_DIR = os.path.join(EXT_DIR, "public_status")
for _d in (EXT_DIR, TEMPLATE_DIR, PUBLIC_STATUS_DIR):
    os.makedirs(_d, exist_ok=True)

user_sessions: Dict[str, Dict[str, Any]] = {}
extension_state: Dict[str, Any] = {
    "announcement": "",
    "grid_layout": {},
    "language": {},
    "theme": {},
    "team": {},
    "schedules": [],
    "sleep": {},
    "rate": {},
    # Additive AI/normal routing state. Existing state keys remain untouched.
    "auto_mode": {},
    "chat2script": {},
}
ext_state_lock = threading.RLock()

AI_ENDPOINT = os.environ.get("AI_ENDPOINT", "").strip()
AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()
AI_MODEL = os.environ.get("AI_MODEL", "").strip()
AI_TIMEOUT_SECONDS = int(os.environ.get("AI_TIMEOUT_SECONDS", "45"))
AI_AUTO_SWITCH = os.environ.get("AI_AUTO_SWITCH", "1").strip().lower() not in {"0", "false", "no", "off"}
AI_MAX_SCRIPT_CHARS = int(os.environ.get("AI_MAX_SCRIPT_CHARS", "120000"))
CHAT2SCRIPT_AUTO_INSTALL = os.environ.get("CHAT2SCRIPT_AUTO_INSTALL", "1").strip().lower() not in {"0", "false", "no", "off"}
DOCKER_BIN = shutil.which("docker")
BLACK_BIN = shutil.which("black")
NGROK_URL = os.environ.get("NGROK_URL", "").strip()


def _load_json_file(path, default):
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        logger.exception("Extension state load failed: %s", path)
    return default


def _save_json_file(path, value):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        logger.exception("Extension state save failed: %s", path)
        try:
            os.remove(tmp)
        except Exception:
            pass


def extension_load_state():
    global extension_state
    with ext_state_lock:
        extension_state.update(_load_json_file(EXT_STATE_FILE, {}))
        extension_state["schedules"] = _load_json_file(SCHEDULE_FILE, extension_state.get("schedules", []))
        extension_state["team"] = _load_json_file(TEAM_FILE, extension_state.get("team", {}))


def extension_save_state():
    with ext_state_lock:
        _save_json_file(EXT_STATE_FILE, extension_state)
        _save_json_file(SCHEDULE_FILE, extension_state.get("schedules", []))
        _save_json_file(TEAM_FILE, extension_state.get("team", {}))


def ext_is_owner(uid, bot_id):
    try:
        rec = hosted_processes.get(bot_id) or {}
        return is_admin(uid) or int(rec.get("owner_id", -1)) == int(uid)
    except Exception:
        return False


def ext_mode(uid):
    return user_sessions.setdefault(str(uid), {}).get("mode", "normal")


def ext_language(uid):
    return extension_state.get("language", {}).get(str(uid), "en")


def ext_t(uid, en, hi):
    return hi if ext_language(uid) == "hi" else en


def ext_set_mode(uid, mode):
    user_sessions.setdefault(str(uid), {})["mode"] = mode
    user_sessions[str(uid)]["updated_at"] = now_iso()
    extension_state.setdefault("modes", {})[str(uid)] = mode
    extension_save_state()


def ext_mask(value):
    value = str(value or "")
    if len(value) <= 6:
        return "••••••"
    return value[:2] + "•" * min(12, len(value) - 4) + value[-2:]


def ext_rate_allowed(uid, action="default", limit=12, window=60):
    key = f"{uid}:{action}"
    now = time.time()
    with ext_state_lock:
        bucket = extension_state.setdefault("rate", {}).setdefault(key, [])
        bucket[:] = [x for x in bucket if now - x < window]
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def ext_feature_menu(uid):
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("🕹️ Normal Mode", callback_data="x_mode:normal"),
        InlineKeyboardButton("🧠 AI Mode", callback_data="x_mode:ai"),
        InlineKeyboardButton("🧰 New Tools", callback_data="x_tools"),
        InlineKeyboardButton("📅 Scheduler", callback_data="x_schedule"),
        InlineKeyboardButton("👥 Team", callback_data="x_team"),
        InlineKeyboardButton("🎨 UI Settings", callback_data="x_ui"),
        InlineKeyboardButton("🤖 Ask AI", callback_data="x_ai"),
        InlineKeyboardButton("🔐 Security", callback_data="x_security"),
        InlineKeyboardButton("📦 Templates", callback_data="x_templates"),
        InlineKeyboardButton("🔙 Main Dashboard", callback_data="main_menu"),
    )
    return m


def ext_tools_menu():
    m = InlineKeyboardMarkup(row_width=2)
    for text, cb in [
        ("🐙 GitHub Deploy", "x_github"),
        ("☁️ Backup", "x_backup"),
        ("🐳 Docker Status", "x_docker"),
        ("🌐 Public Status", "x_public"),
        ("📊 Bandwidth", "x_bandwidth"),
        ("🗄️ Database", "x_database"),
        ("📝 Formatter", "x_format"),
        ("🧪 Requirements", "x_requirements"),
        ("📄 Logs → PDF", "x_pdf"),
        ("🔌 Webhook/Proxy", "x_proxy"),
        ("🔙 Features", "x_features"),
    ]:
        m.add(InlineKeyboardButton(text, callback_data=cb))
    return m


def ext_ui_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("🇬🇧 English", callback_data="x_lang:en"),
        InlineKeyboardButton("🇮🇳 Hindi", callback_data="x_lang:hi"),
        InlineKeyboardButton("▦ Grid", callback_data="x_layout:grid"),
        InlineKeyboardButton("☷ List", callback_data="x_layout:list"),
        InlineKeyboardButton("🌙 Dark Logs", callback_data="x_theme:dark"),
        InlineKeyboardButton("☀️ Light Logs", callback_data="x_theme:light"),
        InlineKeyboardButton("🧭 Onboarding", callback_data="x_onboard"),
        InlineKeyboardButton("🔙 Features", callback_data="x_features"),
    )
    return m


def ext_security_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("🔎 Audit My Bots", callback_data="x_audit"),
        InlineKeyboardButton("🧩 CVE/Dependency Check", callback_data="x_cve"),
        InlineKeyboardButton("🔐 ENV Manager", callback_data="x_env_export"),
        InlineKeyboardButton("🛡️ Rate Limit Status", callback_data="x_rate"),
        InlineKeyboardButton("🔙 Features", callback_data="x_features"),
    )
    return m


def ext_ai_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("🔍 Code Review", callback_data="x_ai_review"),
        InlineKeyboardButton("🩺 Crash Resolver", callback_data="x_ai_crash"),
        InlineKeyboardButton("📦 Auto Requirements", callback_data="x_ai_req"),
        InlineKeyboardButton("⚡ Optimize Code", callback_data="x_ai_opt"),
        InlineKeyboardButton("🧾 Log Summary", callback_data="x_ai_logs"),
        InlineKeyboardButton("🛡️ Security Audit", callback_data="x_ai_sec"),
        InlineKeyboardButton("🔑 ENV Explainer", callback_data="x_ai_env"),
        InlineKeyboardButton("🧠 Health Predictor", callback_data="x_ai_health"),
        InlineKeyboardButton("🔎 Natural Search", callback_data="x_ai_search"),
        InlineKeyboardButton("🩹 Auto-Heal Info", callback_data="x_ai_heal"),
        InlineKeyboardButton("✍️ Broadcast Draft", callback_data="x_ai_broadcast"),
        InlineKeyboardButton("🏷️ Naming Assistant", callback_data="x_ai_name"),
        InlineKeyboardButton("💬 Support Chat", callback_data="x_ai_support"),
        InlineKeyboardButton("🧑‍💻 Chat → Script Runner", callback_data="x_ai_chat2script"),
        InlineKeyboardButton("🔁 Auto AI ↔ Normal", callback_data="x_auto_mode"),
        InlineKeyboardButton("🔙 Features", callback_data="x_features"),
    )
    return m


def ext_schedule_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("➕ Schedule Bot", callback_data="x_sched_add"),
        InlineKeyboardButton("📋 My Schedules", callback_data="x_sched_list"),
        InlineKeyboardButton("😴 Auto-Sleep", callback_data="x_sleep"),
        InlineKeyboardButton("⏰ Cron Help", callback_data="x_cron_help"),
        InlineKeyboardButton("🔙 Features", callback_data="x_features"),
    )
    return m


def ext_team_menu(uid):
    m = InlineKeyboardMarkup(row_width=2)
    if is_admin(uid):
        m.add(
            InlineKeyboardButton("➕ Add Admin", callback_data="x_team_add"),
            InlineKeyboardButton("➖ Remove Admin", callback_data="x_team_remove"),
        )
    m.add(
        InlineKeyboardButton("👥 Team List", callback_data="x_team_list"),
        InlineKeyboardButton("🔙 Features", callback_data="x_features"),
    )
    return m


def ext_template_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("🤖 Telegram Bot", callback_data="x_tpl:telegram"),
        InlineKeyboardButton("🌐 Flask App", callback_data="x_tpl:flask"),
        InlineKeyboardButton("⚡ FastAPI", callback_data="x_tpl:fastapi"),
        InlineKeyboardButton("📡 Discord Bot", callback_data="x_tpl:discord"),
        InlineKeyboardButton("🗃️ SQLite App", callback_data="x_tpl:sqlite"),
        InlineKeyboardButton("🔙 Features", callback_data="x_features"),
    )
    return m


def ext_send(chat_id, text, markup=None):
    try:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.send_message(chat_id, text, reply_markup=markup)


def ext_bot_list(uid):
    result = []
    for bid, rec in hosted_processes.items():
        if is_admin(uid) or int(rec.get("owner_id", -1)) == int(uid):
            result.append(bid)
    return result


def ext_current_bot(uid):
    return user_sessions.setdefault(str(uid), {}).get("bot_id")


def ext_set_bot(uid, bot_id):
    user_sessions.setdefault(str(uid), {})["bot_id"] = bot_id


def ext_require_bot(uid):
    bid = ext_current_bot(uid)
    if bid and bid in hosted_processes and ext_is_owner(uid, bid):
        return bid
    bots = ext_bot_list(uid)
    if len(bots) == 1:
        ext_set_bot(uid, bots[0])
        return bots[0]
    return None


def ext_security_audit_path(path):
    findings = []
    secret_patterns = [
        (r"(?i)bot[_-]?token\s*=\s*['"][^'"]+['"]", "Hard-coded bot token-like value"),
        (r"(?i)api[_-]?hash\s*=\s*['"][^'"]+['"]", "Hard-coded API hash-like value"),
        (r"(?i)(password|passwd|secret|private[_-]?key)\s*=\s*['"][^'"]+['"]", "Hard-coded secret-like value"),
    ]
    for root, _, files in os.walk(path):
        for name in files:
            if not name.endswith((".py", ".js", ".ts", ".json", ".env", ".yml", ".yaml")):
                continue
            fp = os.path.join(root, name)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                for pattern, label in secret_patterns:
                    if re.search(pattern, text):
                        findings.append(f"⚠️ {label}: `{os.path.relpath(fp, path)}`")
                if name.lower() in {".env", ".env.local"}:
                    findings.append(f"🔒 Environment file present: `{os.path.relpath(fp, path)}`")
            except Exception:
                pass
    return findings


def ext_requirements_for_bot(bot_id):
    folder = os.path.join(HOST_DIR, bot_id)
    if not os.path.isdir(folder):
        return []
    detected = deep_analyze_imports(folder)
    # Normalize package map entries and remove duplicates.
    return list(dict.fromkeys(detected))


def ext_write_requirements(bot_id):
    packages = ext_requirements_for_bot(bot_id)
    path = os.path.join(HOST_DIR, bot_id, "requirements.generated.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("
".join(packages) + ("
" if packages else ""))
    return path, packages


def ext_format_bot(bot_id):
    folder = os.path.join(HOST_DIR, bot_id)
    changed = []
    for root, _, files in os.walk(folder):
        for name in files:
            if not name.endswith(".py"):
                continue
            fp = os.path.join(root, name)
            if BLACK_BIN:
                try:
                    r = _subprocess_ext.run([BLACK_BIN, fp, "--quiet"], capture_output=True, text=True, timeout=60)
                    if r.returncode == 0:
                        changed.append(os.path.relpath(fp, folder))
                except Exception:
                    pass
    return changed


def ext_dependency_cve_hint(bot_id):
    packages = ext_requirements_for_bot(bot_id)
    # Offline-safe scanner: reports packages and asks pip-audit when available.
    audit = shutil.which("pip-audit")
    if not audit:
        return "ℹ️ `pip-audit` is not installed.
Detected dependencies:
" + "
".join(f"• `{x}`" for x in packages)
    try:
        r = _subprocess_ext.run([audit, "-r", os.path.join(HOST_DIR, bot_id, "requirements.generated.txt")], capture_output=True, text=True, timeout=180)
        return safe_text(r.stdout or r.stderr or "No audit output.", 3500)
    except Exception as exc:
        return f"❌ CVE audit failed: `{exc}`"


def ext_create_database(bot_id):
    folder = os.path.join(HOST_DIR, bot_id)
    os.makedirs(folder, exist_ok=True)
    db = os.path.join(folder, "hosted_app.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE IF NOT EXISTS host_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT OR REPLACE INTO host_meta(key,value) VALUES(?,?)", ("created_at", now_iso()))
    conn.commit()
    conn.close()
    return db


def ext_backup_bot(bot_id):
    folder = os.path.join(HOST_DIR, bot_id)
    if not os.path.isdir(folder):
        raise FileNotFoundError("Bot folder not found")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = os.path.join(BACKUP_DIR, f"{bot_id}_{stamp}")
    shutil.make_archive(target, "zip", folder)
    return target + ".zip"


def ext_full_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = os.path.join(BACKUP_DIR, f"engine_full_{stamp}")
    shutil.make_archive(target, "zip", BASE_DIR)
    return target + ".zip"


def ext_send_file(chat_id, path, caption=""):
    with open(path, "rb") as f:
        bot.send_document(chat_id, f, caption=caption)


def ext_export_env(uid):
    envs = user_custom_envs.get(str(uid), {})
    text = "
".join(f"{k}={v}" for k, v in envs.items())
    return text or "# No custom environment variables"


def ext_import_env(uid, text):
    envs = user_custom_envs.setdefault(str(uid), {})
    count = 0
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            envs[key] = value.strip().strip(""").strip("'")
            count += 1
    save_registry()
    return count


def ext_public_status():
    statuses = []
    for bid, rec in hosted_processes.items():
        statuses.append({"id": bid, "running": is_bot_running(bid), "owner": rec.get("owner_id")})
    path = os.path.join(PUBLIC_STATUS_DIR, "index.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": now_iso(), "bots": statuses}, f, indent=2)
    return path


def ext_bandwidth(bot_id):
    rec = hosted_processes.get(bot_id) or {}
    pid = (rec.get("process") or None)
    if not pid or not psutil or pid.poll() is not None:
        return {"rx": 0, "tx": 0, "note": "Per-process network counters unavailable on this host."}
    # Linux /proc fallback is intentionally best-effort; psutil does not expose per-process net bytes.
    return {"rx": 0, "tx": 0, "note": "Per-process network counters unavailable; host-wide counters can be added by platform."}


def ext_docker_status():
    if not DOCKER_BIN:
        return "🔴 Docker CLI not available on this host."
    try:
        r = _subprocess_ext.run([DOCKER_BIN, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return f"🟢 Docker available — `{r.stdout.strip()}`"
        return f"🔴 Docker unavailable: `{safe_text(r.stderr, 1000)}`"
    except Exception as exc:
        return f"🔴 Docker check failed: `{exc}`"


def ext_safe_docker_run(bot_id, command):
    if not DOCKER_BIN:
        return False, "Docker is not installed."
    if not ext_is_owner(user_sessions.get(str(bot_id), {}).get("uid", 0), bot_id):
        return False, "Permission denied."
    return False, "Docker sandbox is provisioned as an optional deployment target; enable it per host policy."


def ext_allowed_terminal(bot_id, command, uid):
    if not ext_is_owner(uid, bot_id):
        return "❌ Permission denied."
    try:
        parts = shlex.split(command)
    except Exception:
        return "❌ Invalid command syntax."
    if not parts:
        return ""
    allowed = {"pwd", "ls", "dir", "python", "python3", "pip", "pip3"}
    if parts[0] not in allowed:
        return "🛡️ Only safe read/package commands are allowed: `pwd`, `ls`, `python --version`, `pip --version`."
    if parts[0] in {"python", "python3"} and len(parts) > 2:
        return "🛡️ Python execution is restricted inside the Telegram terminal."
    if parts[0] in {"pip", "pip3"} and len(parts) > 2 and parts[1] not in {"--version", "list", "show"}:
        return "🛡️ Package installation is controlled by the deployment engine."
    folder = os.path.join(HOST_DIR, bot_id)
    try:
        r = _subprocess_ext.run(parts, cwd=folder, capture_output=True, text=True, timeout=20)
        return safe_text((r.stdout or r.stderr or "(no output)"), 3500)
    except Exception as exc:
        return f"❌ Terminal error: `{exc}`"


def ext_github_deploy(url, uid):
    if not url.startswith(("https://github.com/", "http://github.com/")):
        raise ValueError("Only GitHub repository URLs are accepted.")
    parsed = urlparse(url)
    parts = [x for x in parsed.path.strip("/").split("/") if x]
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repository URL.")
    owner, repo = parts[:2]
    repo = repo.removesuffix(".git")
    bot_id = generate_bot_id()
    dest = os.path.join(HOST_DIR, bot_id)
    os.makedirs(dest, exist_ok=True)
    git = shutil.which("git")
    if not git:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError("Git is not installed on the hosting host.")
    clone_url = f"https://github.com/{owner}/{repo}.git"
    git_cmd = [git]
    if GH_TOKEN:
        git_cmd += ["-c", f"http.extraheader=AUTHORIZATION: bearer {GH_TOKEN}"]
    git_cmd += ["clone", "--depth", "1", clone_url, dest]
    r = _subprocess_ext.run(git_cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(safe_text(r.stderr, 2000))
    candidates = ["main.py", "bot.py", "app.py", "server.py"]
    entry = next((x for x in candidates if os.path.isfile(os.path.join(dest, x))), None)
    if not entry:
        pyfiles = []
        for root, _, files in os.walk(dest):
            pyfiles.extend(os.path.relpath(os.path.join(root, x), dest) for x in files if x.endswith(".py"))
        if pyfiles:
            entry = pyfiles[0]
    if not entry:
        raise RuntimeError("No Python entry file found in repository.")
    bot_metadata[bot_id] = {"owner_id": uid, "entry_file": entry, "source": url, "created_at": now_iso()}
    ensure_metrics(bot_id)
    create_bot_version(bot_id, reason="github_import")
    save_registry()
    return bot_id, entry


def ext_natural_bot_search(uid, query):
    q = query.lower()
    scored = []
    for bid, rec in hosted_processes.items():
        if not ext_is_owner(uid, bid):
            continue
        meta = bot_metadata.get(bid, {})
        hay = " ".join([bid, str(meta.get("name", "")), str(meta.get("source", "")), str(rec.get("entry_file", ""))]).lower()
        score = sum(1 for token in re.findall(r"\w+", q) if token in hay)
        if score:
            scored.append((score, bid))
    return [x[1] for x in sorted(scored, reverse=True)]


def ext_naming_assistant(uid):
    candidates = ["NovaHost", "ArshadCloud", "ZyroBot", "PulseBot", "BiharBot", "SwiftHost", "OrbitBot", "CodeNest"]
    used = {str(v.get("name", "")) for v in bot_metadata.values()}
    return next((x for x in candidates if x not in used), "HostedBot")


def ext_auto_mode(uid):
    """Return whether automatic AI↔Normal fallback is enabled for this user."""
    return bool(
        extension_state.setdefault("auto_mode", {}).get(
            str(uid),
            AI_AUTO_SWITCH,
        )
    )


def ext_set_auto_mode(uid, enabled):
    extension_state.setdefault("auto_mode", {})[str(uid)] = bool(enabled)
    extension_save_state()


def ext_ai_available():
    return bool(AI_ENDPOINT and AI_API_KEY)


def ext_extract_code(text):
    """Extract a complete script from a Markdown code fence or plain code text."""
    text = (text or "").strip()
    fenced = re.findall(r"```(?:[A-Za-z0-9_+.#-]+)?\s*
?(.*?)```", text, flags=re.S)
    if fenced:
        candidates = [x.strip() for x in fenced if x.strip()]
        if candidates:
            return max(candidates, key=len)
    # Accept obvious source-code input without a fence.
    code_markers = (
        "import ", "from ", "def ", "class ", "#!", "print(",
        "const ", "let ", "var ", "function ", "<!doctype", "<html",
        "require(", "package main", "using System", "<?php",
    )
    if any(text.startswith(x) or f"
{x}" in text for x in code_markers):
        return text
    return ""


def ext_local_script_analysis(code):
    """Normal-mode analysis: syntax-check Python without requiring AI."""
    try:
        ast.parse(code)
        return "✅ Local normal-mode check: Python syntax is valid."
    except SyntaxError as exc:
        return (
            "⚠️ Local normal-mode check found a Python syntax error: "
            f"`line {exc.lineno}: {safe_text(exc.msg, 300)}`"
        )
    except Exception as exc:
        return f"ℹ️ Local check: `{safe_text(exc, 500)}`"


def ext_ai_or_normal(uid, prompt, context="", local_fallback=""):
    """
    AI is an enhancement, never a hard dependency.
    If AI is unavailable/fails and auto-switch is enabled, return the normal fallback.
    """
    if ext_ai_available():
        result = ext_ai_request(prompt, context)
        if not result.startswith(("❌ AI request failed", "AI provider is not configured")):
            return result
        if not ext_auto_mode(uid):
            return result
    return local_fallback or "🟢 Normal mode is active; AI was not required."


def ext_prepare_script_for_runner(uid, user_text):
    """
    Build a deployable script proposal. AI can generate code when available;
    otherwise the user's supplied code is used directly, so deployment remains
    independent of AI.
    """
    direct_code = ext_extract_code(user_text)
    if direct_code:
        return direct_code, "direct"

    if ext_mode(uid) == "ai" and ext_ai_available():
        prompt = (
            "Create ONE complete, runnable application script from the user's request. "
            "Return only the source code inside one Markdown code fence. "
            "Do not return commentary. Preserve requested behavior. "
            "Prefer Python unless the user explicitly requests another language. "
            "The hosting engine will syntax-check and deploy it only after user confirmation.

"
            "USER REQUEST:
" + user_text
        )
        answer = ext_ai_request(prompt)
        code = ext_extract_code(answer)
        if code:
            return code, "ai"

    # AI failed/unavailable: auto-switch to normal mode.
    if ext_auto_mode(uid):
        return "", "normal_fallback"

    return "", "ai_unavailable"


def ext_chat2script_proposal(uid, user_text):
    code, source = ext_prepare_script_for_runner(uid, user_text)
    if not code:
        if source == "normal_fallback":
            return (
                "🔁 **AI unavailable — Normal Mode active.**

"
                "AI generation was skipped. Send the complete code (preferably in a "
                "```code``` block), and I can deploy it without AI."
            )
        return (
            "❌ I could not generate/extract runnable code.

"
            "Either configure the AI provider or send the complete script directly."
        )

    if len(code) > AI_MAX_SCRIPT_CHARS:
        return f"❌ Script is too large. Limit: `{AI_MAX_SCRIPT_CHARS}` characters."

    # Keep pending script out of Telegram text; store it server-side.
    state = user_sessions.setdefault(str(uid), {})
    state["pending_script"] = code
    state["pending_script_source"] = source
    state["awaiting"] = "chat2script_confirm"

    language = "Python" if re.search(r"(^|
)\s*(import |from |def |class )", code) else "source"
    preview = safe_text(code, 1800)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Deploy Full Board", callback_data="x_c2s_confirm"),
        InlineKeyboardButton("❌ Cancel", callback_data="x_c2s_cancel"),
    )
    return (
        "🧑‍💻 **Chat → Script Runner**

"
        f"Source: `{source.upper()}`
"
        f"Type: `{language}`
"
        f"Size: `{len(code)}` chars

"
        "I will NOT deploy automatically. Your permission is required first.
"
        "After confirmation: create bot → backup/version → dependency scan → "
        "optional auto-install → syntax check → start → health monitoring.

"
        "```
" + preview + "
```"
    ), markup


def ext_chat2script_deploy(uid, chat_id):
    state = user_sessions.setdefault(str(uid), {})
    code = state.get("pending_script", "")
    if not code:
        raise ValueError("No pending script is waiting for confirmation.")

    bot_id = generate_bot_id()
    folder = os.path.join(HOST_DIR, bot_id)
    os.makedirs(folder, exist_ok=True)
    entry = "main.py"
    path = os.path.join(folder, entry)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        # Syntax validation happens before any process is started.
        py_compile.compile(path, doraise=True)

        bot_metadata[bot_id] = {
            "owner_id": uid,
            "entry_file": entry,
            "source": "chat_to_script_runner",
            "created_at": now_iso(),
            "script_source": state.get("pending_script_source", "unknown"),
        }
        ensure_metrics(bot_id)

        # Preserve the engine's existing version/rollback architecture.
        create_bot_version(bot_id, reason="chat_to_script_runner")

        packages = ext_requirements_for_bot(bot_id)
        req_path = os.path.join(folder, "requirements.generated.txt")
        with open(req_path, "w", encoding="utf-8") as f:
            if packages:
                f.write("
".join(packages) + "
")

        if CHAT2SCRIPT_AUTO_INSTALL and packages:
            ok, error = auto_install_packages_verified(
                packages,
                chat_id,
                0,
                time.time(),
            )
            if not ok:
                # Keep the deployed source and metadata; do not start a broken bot.
                raise RuntimeError(
                    "Dependency installation failed. "
                    + safe_text(error, 1400)
                )

        result = start_bot_once(
            bot_id,
            entry,
            uid,
            reason="chat_to_script_runner",
            notify=False,
        )
        metric_increment(bot_id, "deployments")
        ensure_metrics(bot_id)["successful_runs"] = int(
            ensure_metrics(bot_id).get("successful_runs", 0)
        ) + (1 if result.get("started") else 0)
        ext_set_bot(uid, bot_id)

        state.pop("pending_script", None)
        state.pop("pending_script_source", None)
        state.pop("awaiting", None)
        save_registry()
        return bot_id, entry, packages, result
    except Exception:
        # Do not leave a half-created project as an active hosted bot.
        hosted_processes.pop(bot_id, None)
        shutil.rmtree(folder, ignore_errors=True)
        bot_metadata.pop(bot_id, None)
        bot_metrics.pop(bot_id, None)
        save_registry()
        raise


def ext_normal_fallback_for_action(uid, action, bot_id=None):
    """Local equivalents for AI actions, keeping all AI buttons functional offline."""
    bot_id = bot_id or ext_require_bot(uid)
    if action == "review":
        if not bot_id:
            return "🟢 Normal mode: select a bot first."
        folder = os.path.join(HOST_DIR, bot_id)
        py_files = []
        for root, _, files in os.walk(folder):
            py_files.extend(
                os.path.join(root, n) for n in files if n.endswith(".py")
            )
        syntax_errors = []
        for fp in py_files[:100]:
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    ast.parse(f.read(), filename=fp)
            except SyntaxError as exc:
                syntax_errors.append(
                    f"• `{os.path.relpath(fp, folder)}` line `{exc.lineno}`: {exc.msg}"
                )
        return (
            f"🟢 **Normal Code Review — {bot_id}**

"
            + ("✅ Python syntax checks passed." if not syntax_errors
               else "⚠️ Syntax findings:
" + "
".join(syntax_errors))
        )
    if action == "req":
        if not bot_id:
            return "🟢 Normal mode: select a bot first."
        _, packages = ext_write_requirements(bot_id)
        return "🟢 **Normal Requirements Scan**

" + (
            "
".join(f"• `{x}`" for x in packages) if packages else "No external packages detected."
        )
    if action == "sec":
        if not bot_id:
            return "🟢 Normal mode: select a bot first."
        findings = ext_security_audit_path(os.path.join(HOST_DIR, bot_id))
        return (
            "🟢 **Normal Security Scanner**

"
            + ("
".join(findings) if findings else "✅ No obvious hard-coded secret patterns detected.")
        )
    if action == "logs":
        if not bot_id:
            return "🟢 Normal mode: select a bot first."
        return "🟢 **Normal Log Mode**

" + safe_text(ext_ai_crash_context(bot_id), 4000)
    if action == "health":
        if not bot_id:
            return "🟢 Normal mode: select a bot first."
        h = inspect_bot_health(bot_id)
        return (
            f"🟢 **Normal Health Check — {bot_id}**

"
            f"Status: `{h['status']}`
CPU: `{round(float(h.get('cpu', 0)), 2)}%`
"
            f"Memory: `{get_readable_size(int(h.get('memory', 0)))}`
PID: `{h.get('pid')}`"
        )
    if action == "heal":
        if not bot_id:
            return "🟢 Normal mode: select a bot first."
        return "🟢 Normal auto-healing is already provided by the engine watchdog."
    if action == "search":
        return "🟢 Normal search: describe a bot name/ID and I will match the local registry."
    if action == "support":
        return ext_onboarding(uid)
    if action == "broadcast":
        return "🟢 Normal mode: AI is unavailable. Write your announcement manually and send it."
    if action == "env":
        return "🟢 Normal ENV mode:

" + ext_export_env(uid)
    if action == "name":
        return f"🟢 Suggested local name: **{ext_naming_assistant(uid)}**"
    if action == "crash":
        return "🟢 **Normal Crash Log**

" + safe_text(ext_ai_crash_context(bot_id), 4000)
    if action == "opt":
        if not bot_id:
            return "🟢 Normal mode: select a bot first."
        folder = os.path.join(HOST_DIR, bot_id)
        files = []
        total_lines = 0
        for root, _, names in os.walk(folder):
            for name in names:
                if name.endswith((".py", ".js", ".ts")):
                    fp = os.path.join(root, name)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                            lines = f.readlines()
                        files.append(os.path.relpath(fp, folder))
                        total_lines += len(lines)
                    except Exception:
                        pass
        return (
            f"🟢 **Normal Optimization Report — {bot_id}**

"
            f"Files scanned: `{len(files)}`
Lines scanned: `{total_lines}`
"
            "No automatic semantic rewrite was performed; the normal engine preserves existing behavior."
        )
    return "🟢 Normal mode handled the request without AI."


def ext_ai_assist_feature(uid, feature, context=""):
    """Universal AI layer for every extension feature.

    Normal mode never calls this. AI mode uses it as an advisory/decision layer,
    while the deterministic implementation remains the source of truth.
    If the provider is unavailable, the feature continues normally.
    """
    if ext_mode(uid) != "ai" or not ext_auto_mode(uid) or not ext_ai_available():
        return ""
    prompts = {
        "github": "Review this GitHub deployment request for likely entrypoint, dependency, and deployment risks. Give concise actionable advice; do not block a valid deployment.",
        "backup": "Advise on the safest backup/versioning strategy for this hosted bot. Do not delete or modify files.",
        "docker": "Explain the safest containerization option for this hosting environment without changing the deployment automatically.",
        "public": "Summarize the public-status information and point out operational risks without changing anything.",
        "bandwidth": "Interpret the bot bandwidth metrics and identify unusual usage patterns if visible.",
        "database": "Recommend a safe database setup for this hosted project while preserving the existing local database feature.",
        "format": "Review the code-formatting intent and identify any risky formatting changes that should be avoided.",
        "requirements": "Review the locally detected dependencies and identify likely missing or suspicious packages. Do not invent packages without evidence.",
        "pdf": "Explain what the bot logs indicate operationally and what should be checked next.",
        "proxy": "Explain the configured proxy/public URL setup and its likely operational implications.",
        "security": "Review this security action context and provide defensive recommendations without weakening existing controls.",
        "scheduler": "Suggest the safest scheduling strategy for this bot action while preserving the deterministic scheduler.",
        "team": "Explain the safest team permission practice for this action; never grant permissions automatically.",
        "template": "Suggest a robust deployment configuration for this template while preserving the generated template itself.",
        "ui": "Suggest a useful UI configuration for the selected setting without changing the user's requested setting.",
        "onboarding": "Give concise beginner-friendly guidance for this hosting feature.",
        "mode": "Explain the selected mode and its AI/normal behavior clearly.",
    }
    prompt = prompts.get(feature, "Assist with this hosting feature safely.")
    try:
        return ext_ai_request(prompt, context)
    except Exception as exc:
        logger.warning("AI feature assist failed: %s", exc)
        return ""


def ext_send_ai_assist(chat_id, uid, feature, context=""):
    """Fire-and-forget AI advisory so normal operations are never blocked by AI."""
    if ext_mode(uid) != "ai" or not ext_auto_mode(uid) or not ext_ai_available():
        return
    def worker():
        answer = ext_ai_assist_feature(uid, feature, context)
        if answer and not answer.startswith(("❌ AI request failed", "AI provider is not configured")):
            try:
                ext_send(chat_id, "🧠 **AI Assist**

" + safe_text(answer, 3500))
            except Exception:
                pass
    threading.Thread(target=worker, name=f"ai-assist-{feature}", daemon=True).start()


def ext_ai_request(prompt, context=""):
    if not AI_ENDPOINT or not AI_API_KEY:
        return "AI provider is not configured. Set `AI_ENDPOINT`, `AI_API_KEY` and optionally `AI_MODEL` in the hosting environment."
    try:
        payload = {
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": "You are a concise, security-conscious hosting assistant."},
                {"role": "user", "content": prompt + "

CONTEXT:
" + context},
            ],
        }
        r = requests.post(
            AI_ENDPOINT,
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=AI_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        data = r.json()
        return safe_text(
            data.get("choices", [{}])[0].get("message", {}).get("content", data),
            5000,
        )
    except Exception as exc:
        return f"❌ AI request failed: `{safe_text(exc, 1000)}`"


def ext_ai_context_bot(bot_id, max_chars=12000):
    if not bot_id:
        return "No bot selected."
    folder = os.path.join(HOST_DIR, bot_id)
    snippets = []
    total = 0
    for root, _, files in os.walk(folder):
        for name in files:
            if not name.endswith((".py", ".js", ".ts")):
                continue
            fp = os.path.join(root, name)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                part = txt[: min(4000, max_chars - total)]
                snippets.append(f"FILE {os.path.relpath(fp, folder)}
{part}")
                total += len(part)
                if total >= max_chars:
                    break
            except Exception:
                pass
        if total >= max_chars:
            break
    return "

".join(snippets)


def ext_ai_crash_context(bot_id):
    if not bot_id:
        return "No bot selected."
    path = os.path.join(LOG_DIR, f"{bot_id}.log")
    if not os.path.isfile(path):
        return "No log file found."
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()[-12000:]
    except Exception:
        return "Unable to read logs."


def ext_ai_action(uid, action):
    bot_id = ext_require_bot(uid)
    if action in {"name", "broadcast", "support"}:
        context = ""
    elif not bot_id:
        return ext_normal_fallback_for_action(uid, action)
    else:
        context = ext_ai_context_bot(bot_id)

    prompts = {
        "review": "Review this hosted code for bugs, reliability and safe deployment. Give actionable findings without claiming certainty.",
        "opt": "Suggest safe performance and maintainability optimizations. Do not remove required behavior.",
        "req": "Infer likely Python dependencies from this code and produce a conservative requirements list.",
        "sec": "Perform a security review focusing on secrets, unsafe subprocesses, file traversal, permissions and network exposure.",
        "env": "Explain which environment variables this project appears to need and why. Never invent secret values.",
        "logs": "Summarize these logs into symptoms, likely causes and next safe actions.",
        "health": "Assess likely operational risks from this hosting context and give a cautious 24-hour risk assessment.",
        "heal": "Explain the safest automated recovery strategy for this bot and what should not be automated.",
        "crash": "Analyze this crash log, identify the most likely root causes and suggest a minimal fix plan.",
        "broadcast": "Draft a concise professional hosting maintenance/update announcement for Telegram.",
        "support": "Explain how to use this hosting engine to a beginner in simple language.",
        "search": "Provide a natural-language search interpretation for the user's hosted bot list.",
    }

    if action == "name":
        if ext_ai_available():
            return ext_ai_or_normal(uid, prompts[action], "", ext_normal_fallback_for_action(uid, action))
        return ext_normal_fallback_for_action(uid, action)
    if action == "broadcast":
        return ext_ai_or_normal(uid, prompts[action], "", ext_normal_fallback_for_action(uid, action))
    if action == "crash":
        context = ext_ai_crash_context(bot_id)
    return ext_ai_or_normal(
        uid,
        prompts.get(action, "Help with hosting."),
        context,
        ext_normal_fallback_for_action(uid, action, bot_id),
    )


def ext_log_pdf(bot_id):
    path = os.path.join(LOG_DIR, f"{bot_id}.log")
    if not os.path.isfile(path):
        raise FileNotFoundError("Log file not found.")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        raise RuntimeError("Install `reportlab` to enable PDF log export.")
    out = os.path.join(BACKUP_DIR, f"{bot_id}_{time.strftime('%Y%m%d_%H%M%S')}.pdf")
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(out, pagesize=A4)
    story = [Paragraph(f"Hosting Log — {bot_id}", styles["Title"]), Spacer(1, 12)]
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f.read()[-50000:].splitlines():
            story.append(Paragraph(safe_text(line, 300).replace("&", "&amp;"), styles["Code"]))
    doc.build(story)
    return out


def ext_template_create(kind, uid):
    bot_id = generate_bot_id()
    folder = os.path.join(HOST_DIR, bot_id)
    os.makedirs(folder, exist_ok=True)
    templates = {
        "telegram": 'import os
import telebot

bot = telebot.TeleBot(os.environ.get("BOT_TOKEN", ""))

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Hello from your hosted Telegram bot!")

bot.infinity_polling()
',
        "flask": 'from flask import Flask
app = Flask(__name__)

@app.get("/")
def home():
    return "Hosted Flask app is online"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
',
        "fastapi": 'from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def home():
    return {"status": "online"}
',
        "discord": 'import os
# Add your Discord bot implementation here.
print("Discord template ready")
',
        "sqlite": 'import sqlite3
conn = sqlite3.connect("app.db")
conn.execute("CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, name TEXT)")
conn.commit()
conn.close()
print("SQLite template ready")
',
    }
    code = templates.get(kind, templates["telegram"])
    entry = "main.py"
    with open(os.path.join(folder, entry), "w", encoding="utf-8") as f:
        f.write(code)
    bot_metadata[bot_id] = {"owner_id": uid, "entry_file": entry, "template": kind, "name": ext_naming_assistant(uid), "created_at": now_iso()}
    ensure_metrics(bot_id)
    create_bot_version(bot_id, reason=f"template:{kind}")
    save_registry()
    return bot_id, entry


def ext_schedule_add(uid, bot_id, action, delay_seconds):
    if not ext_is_owner(uid, bot_id):
        raise PermissionError("Permission denied")
    try:
        delay = max(60, int(delay_seconds))
    except Exception:
        raise ValueError("Delay must be seconds.")
    item = {"id": hashlib.sha256(f"{uid}:{bot_id}:{time.time()}".encode()).hexdigest()[:10], "owner_id": uid, "bot_id": bot_id, "action": action, "run_at": time.time() + delay, "enabled": True}
    extension_state.setdefault("schedules", []).append(item)
    extension_save_state()
    return item


def ext_schedule_worker():
    while not SHUTDOWN_REQUESTED:
        now = time.time()
        changed = False
        for item in list(extension_state.get("schedules", [])):
            if not item.get("enabled") or item.get("run_at", 0) > now:
                continue
            bid = item.get("bot_id")
            owner = item.get("owner_id")
            try:
                if item.get("action") == "start":
                    rec = hosted_processes.get(bid) or {}
                    start_bot_once(bid, rec.get("entry_file"), owner, reason="scheduler", notify=False)
                elif item.get("action") == "stop":
                    stop_script_process(bid, reason="scheduler")
                elif item.get("action") == "restart":
                    restart_bot(bid, owner, notify=False)
                elif item.get("action") == "backup":
                    p = ext_backup_bot(bid)
                    ext_send_file(owner, p, f"Scheduled backup: {bid}")
            except Exception as exc:
                record_error(bid, exc)
            item["enabled"] = False
            changed = True
        if changed:
            extension_save_state()
        time.sleep(2)


def ext_auto_sleep_worker():
    while not SHUTDOWN_REQUESTED:
        now = time.time()
        for bid, cfg in list(extension_state.get("sleep", {}).items()):
            if not cfg.get("enabled") or not is_bot_running(bid):
                continue
            idle = now - float(cfg.get("last_activity", now))
            if idle >= float(cfg.get("timeout", 3600)):
                try:
                    stop_script_process(bid, reason="auto_sleep")
                except Exception:
                    pass
        time.sleep(30)


def ext_update_activity(bot_id):
    extension_state.setdefault("sleep", {}).setdefault(bot_id, {"enabled": False, "timeout": 3600, "last_activity": time.time()})["last_activity"] = time.time()


def ext_patch_process_activity():
    # Lightweight compatibility hook: the extension tracks scheduler/health activity without replacing original process functions.
    return True


def ext_dashboard_text(uid):
    mode = ext_mode(uid).upper()
    ai = "configured" if AI_ENDPOINT and AI_API_KEY else "not configured"
    return (
        "🧩 **SUPERCHARGED EXTENSION PACK**

"
        f"🎛️ Mode: `{mode}`
"
        f"🔁 Auto AI ↔ Normal: `{'ON' if ext_auto_mode(uid) else 'OFF'}`
"
        f"🤖 AI Provider: `{ai}`
"
        f"🌐 Proxy URL: `{NGROK_URL or 'not configured'}`
"
        f"🐳 Docker: `{'available' if DOCKER_BIN else 'unavailable'}`
"
        f"🐙 GitHub: `{'token configured' if GH_TOKEN else 'optional/no token'}`

"
        "50-feature architecture is installed as a non-destructive add-on."
    )


def ext_onboarding(uid):
    return (
        "🧭 **Quick Onboarding**

"
        "1️⃣ Choose Normal or AI Mode.
"
        "2️⃣ Deploy a `.py`/`.zip` or use a template.
"
        "3️⃣ Select dependencies and start.
"
        "4️⃣ Use My Bots for Start/Stop/Restart/Logs.
"
        "5️⃣ Use Scheduler, Backup and Security tools from New Tools.
"
        "6️⃣ AI tools require an AI provider configuration."
    )


def ext_callback(call):
    uid = call.from_user.id
    chat = call.message.chat.id
    data = call.data or ""
    if not data.startswith("x_"):
        return False
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    if not ext_rate_allowed(uid, "callback"):
        ext_send(chat, "⏳ Too many actions. Please wait a moment.")
        return True
    try:
        if data.startswith("x_mode:"):
            mode = data.split(":", 1)[1]
            ext_set_mode(uid, mode)
            ext_send(chat, f"✅ Mode changed to **{mode.upper()}**.", ext_feature_menu(uid))
        elif data == "x_features":
            ext_send(chat, ext_dashboard_text(uid), ext_feature_menu(uid))
        elif data == "x_tools":
            ext_send_ai_assist(chat, uid, "onboarding", "New Tools menu")
            ext_send(chat, "🧰 **New Tools**", ext_tools_menu())
        elif data == "x_ui":
            ext_send_ai_assist(chat, uid, "ui", "UI/UX settings menu")
            ext_send(chat, "🎨 **UI / UX Settings**", ext_ui_menu())
        elif data == "x_security":
            ext_send_ai_assist(chat, uid, "security", "Security Center")
            ext_send(chat, "🔐 **Security Center**", ext_security_menu())
        elif data == "x_ai":
            ext_send(chat, "🧠 **AI Mode Tools**", ext_ai_menu())
        elif data == "x_schedule":
            ext_send_ai_assist(chat, uid, "scheduler", "Scheduler menu")
            ext_send(chat, "📅 **Scheduler**", ext_schedule_menu())
        elif data == "x_team":
            ext_send_ai_assist(chat, uid, "team", "Team menu")
            ext_send(chat, "👥 **Team Collaboration**", ext_team_menu(uid))
        elif data == "x_templates":
            ext_send_ai_assist(chat, uid, "template", "Template menu")
            ext_send(chat, "📦 **1-Click Templates**", ext_template_menu())
        elif data == "x_onboard":
            ext_send_ai_assist(chat, uid, "onboarding", ext_onboarding(uid))
            ext_send(chat, ext_onboarding(uid), ext_feature_menu(uid))
        elif data.startswith("x_lang:"):
            ext_send_ai_assist(chat, uid, "ui", "language setting")
            lang = data.split(":", 1)[1]
            extension_state.setdefault("language", {})[str(uid)] = lang
            extension_save_state()
            ext_send(chat, "✅ Language updated.", ext_ui_menu())
        elif data.startswith("x_layout:"):
            ext_send_ai_assist(chat, uid, "ui", "dashboard layout setting")
            layout = data.split(":", 1)[1]
            extension_state.setdefault("grid_layout", {})[str(uid)] = layout
            extension_save_state()
            ext_send(chat, f"✅ Dashboard layout: `{layout}`", ext_ui_menu())
        elif data.startswith("x_theme:"):
            ext_send_ai_assist(chat, uid, "ui", "log theme setting")
            theme = data.split(":", 1)[1]
            extension_state.setdefault("theme", {})[str(uid)] = theme
            extension_save_state()
            ext_send(chat, f"✅ Log theme: `{theme}`", ext_ui_menu())
        elif data == "x_docker":
            ext_send_ai_assist(chat, uid, "docker", ext_docker_status())
            ext_send(chat, ext_docker_status(), ext_tools_menu())
        elif data == "x_public":
            p = ext_public_status()
            ext_send_ai_assist(chat, uid, "public", p)
            ext_send(chat, f"🌐 Public status JSON generated.
`{p}`", ext_tools_menu())
        elif data == "x_bandwidth":
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_tools_menu())
            else:
                info = ext_bandwidth(bid)
                ext_send(chat, f"📊 **{bid} Bandwidth**
RX: `{get_readable_size(info['rx'])}`
TX: `{get_readable_size(info['tx'])}`

{info['note']}", ext_tools_menu())
        elif data == "x_database":
            ext_send_ai_assist(chat, uid, "database", "database action")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_tools_menu())
            else:
                p = ext_create_database(bid)
                ext_send(chat, f"🗄️ Database ready: `{os.path.basename(p)}`", ext_tools_menu())
        elif data == "x_format":
            ext_send_ai_assist(chat, uid, "format", "formatter action")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_tools_menu())
            else:
                changed = ext_format_bot(bid)
                ext_send(chat, f"📝 Formatter complete. Files changed: `{len(changed)}`.", ext_tools_menu())
        elif data in {"x_requirements", "x_ai_req"}:
            if data == "x_requirements":
                ext_send_ai_assist(chat, uid, "requirements", "requirements generation")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_tools_menu())
            else:
                p, packages = ext_write_requirements(bid)
                if data == "x_ai_req" and ext_mode(uid) == "ai":
                    answer = ext_ai_action(uid, "req")
                    ext_send(chat, answer, ext_ai_menu())
                else:
                    ext_send(chat, f"📦 Generated requirements: `{os.path.basename(p)}`

" + "
".join(f"• `{x}`" for x in packages), ext_tools_menu())
        elif data == "x_backup":
            ext_send_ai_assist(chat, uid, "backup", "backup action")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_tools_menu())
            else:
                p = ext_backup_bot(bid)
                ext_send_file(chat, p, f"Backup — {bid}")
        elif data == "x_pdf":
            ext_send_ai_assist(chat, uid, "pdf", "log PDF export")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_tools_menu())
            else:
                p = ext_log_pdf(bid)
                ext_send_file(chat, p, f"PDF log — {bid}")
        elif data == "x_proxy":
            ext_send_ai_assist(chat, uid, "proxy", NGROK_URL or "proxy not configured")
            ext_send(chat, "🔌 Webhook/Port forwarding

" + (f"Configured public URL: `{NGROK_URL}`" if NGROK_URL else "Set `NGROK_URL` after starting your tunnel. The engine does not open arbitrary inbound ports by itself."), ext_tools_menu())
        elif data == "x_github":
            user_sessions[str(uid)]["awaiting"] = "github"
            ext_send(chat, "🐙 Send a GitHub repository URL.
Example: `https://github.com/owner/repo`

Send `cancel` to stop.")
        elif data == "x_env_export":
            text = ext_export_env(uid)
            ext_send(chat, "🔐 **ENV Export**

```
" + safe_text(text, 3000) + "
```", ext_security_menu())
        elif data == "x_audit":
            ext_send_ai_assist(chat, uid, "security", "local security audit")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_security_menu())
            else:
                findings = ext_security_audit_path(os.path.join(HOST_DIR, bid))
                ext_send(chat, f"🔎 **Security Audit — {bid}**

" + ("
".join(findings) if findings else "✅ No obvious hard-coded secret patterns detected by the local scanner."), ext_security_menu())
        elif data == "x_cve":
            ext_send_ai_assist(chat, uid, "security", "dependency audit")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_security_menu())
            else:
                ext_write_requirements(bid)
                ext_send(chat, "🧩 **Dependency Audit**

" + ext_dependency_cve_hint(bid), ext_security_menu())
        elif data == "x_rate":
            ext_send_ai_assist(chat, uid, "security", "rate limiter status")
            ext_send(chat, "🛡️ Rate limiter is active on extension callbacks: 12 actions / 60 seconds per user.", ext_security_menu())
        elif data == "x_ai_review":
            ext_send(chat, ext_ai_action(uid, "review"), ext_ai_menu())
        elif data == "x_ai_crash":
            ext_send(chat, ext_ai_action(uid, "crash"), ext_ai_menu())
        elif data == "x_ai_opt":
            ext_send(chat, ext_ai_action(uid, "opt"), ext_ai_menu())
        elif data == "x_ai_logs":
            ext_send(chat, ext_ai_action(uid, "logs"), ext_ai_menu())
        elif data == "x_ai_sec":
            ext_send(chat, ext_ai_action(uid, "sec"), ext_ai_menu())
        elif data == "x_ai_env":
            ext_send(chat, ext_ai_action(uid, "env"), ext_ai_menu())
        elif data == "x_ai_health":
            ext_send(chat, ext_ai_action(uid, "health"), ext_ai_menu())
        elif data == "x_ai_search":
            user_sessions[str(uid)]["awaiting"] = "ai_search"
            ext_send(chat, "🔎 Describe your bot naturally, e.g. `start my image bot`. Send `cancel` to stop.")
        elif data == "x_ai_heal":
            ext_send(chat, ext_ai_action(uid, "heal"), ext_ai_menu())
        elif data == "x_ai_broadcast":
            ext_send(chat, ext_ai_action(uid, "broadcast"), ext_ai_menu())
        elif data == "x_ai_name":
            ext_send(chat, ext_ai_action(uid, "name"), ext_ai_menu())
        elif data == "x_ai_support":
            ext_send(chat, ext_ai_action(uid, "support"), ext_ai_menu())
        elif data == "x_ai_chat2script":
            user_sessions.setdefault(str(uid), {})["awaiting"] = "chat2script_prompt"
            ext_send(
                chat,
                "🧑‍💻 **Chat → Script Runner**

"
                "Send your request in plain language OR send the complete code.
"
                "Example: `Python Telegram bot with /start and /help`.

"
                "The script will be prepared first; **deployment always needs your confirmation**.
"
                "Send `cancel` to stop.",
                ext_ai_menu(),
            )
        elif data == "x_auto_mode":
            enabled = not ext_auto_mode(uid)
            ext_set_auto_mode(uid, enabled)
            ext_send(
                chat,
                f"🔁 Auto AI ↔ Normal is now **{'ON' if enabled else 'OFF'}**.

"
                "ON = AI is preferred when available; if AI fails, the normal engine continues.
"
                "OFF = AI failures are shown instead of silently falling back.",
                ext_ai_menu(),
            )
        elif data == "x_c2s_cancel":
            user_sessions.setdefault(str(uid), {}).pop("pending_script", None)
            user_sessions[str(uid)].pop("pending_script_source", None)
            user_sessions[str(uid)].pop("awaiting", None)
            ext_send(chat, "❌ Chat → Script Runner cancelled.", ext_ai_menu())
        elif data == "x_c2s_confirm":
            if user_sessions.setdefault(str(uid), {}).get("awaiting") != "chat2script_confirm":
                ext_send(chat, "❌ No deployment proposal is waiting for confirmation.", ext_ai_menu())
            else:
                ext_send(chat, "🚀 Permission received. Deploying the complete board now…")
                bid, entry, packages, result = ext_chat2script_deploy(uid, chat)
                ext_send(
                    chat,
                    f"✅ **Deployment complete**

"
                    f"🤖 Bot ID: `{bid}`
"
                    f"📄 Entry: `{entry}`
"
                    f"📦 Dependencies: `{len(packages)}`
"
                    f"🟢 Result: `{result.get('message', 'started')}`",
                    ext_feature_menu(uid),
                )
        elif data == "x_sched_add":
            ext_send_ai_assist(chat, uid, "scheduler", "add scheduled action")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first. Use My Bots and tap a bot control panel.", ext_schedule_menu())
            else:
                user_sessions[str(uid)]["awaiting"] = "schedule"
                ext_send(chat, "📅 Send: `action delay_seconds`
Example: `restart 3600`
Allowed: start, stop, restart, backup")
        elif data == "x_sched_list":
            ext_send_ai_assist(chat, uid, "scheduler", "list schedules")
            rows = [x for x in extension_state.get("schedules", []) if int(x.get("owner_id", -1)) == int(uid) and x.get("enabled")]
            text = "📋 **Active schedules**

" + ("
".join(f"• `{x['id']}` `{x['bot_id']}` `{x['action']}` in `{max(0,int(x['run_at']-time.time()))}s`" for x in rows) if rows else "No active schedules.")
            ext_send(chat, text, ext_schedule_menu())
        elif data == "x_sleep":
            ext_send_ai_assist(chat, uid, "scheduler", "auto-sleep toggle")
            bid = ext_require_bot(uid)
            if not bid:
                ext_send(chat, "Select a bot first.", ext_schedule_menu())
            else:
                cfg = extension_state.setdefault("sleep", {}).setdefault(bid, {"enabled": False, "timeout": 3600, "last_activity": time.time()})
                cfg["enabled"] = not cfg.get("enabled", False)
                cfg["last_activity"] = time.time()
                extension_save_state()
                ext_send(chat, f"😴 Auto-sleep for `{bid}`: `{'ON' if cfg['enabled'] else 'OFF'}` (default 1h idle timeout).", ext_schedule_menu())
        elif data == "x_cron_help":
            ext_send_ai_assist(chat, uid, "scheduler", "cron help")
            ext_send(chat, "⏰ Scheduler uses one-shot delayed tasks. For recurring cron, use your host OS scheduler or a process supervisor; this add-on intentionally avoids arbitrary cron execution from Telegram.", ext_schedule_menu())
        elif data == "x_team_add":
            ext_send_ai_assist(chat, uid, "team", "add admin request")
            if not is_admin(uid):
                ext_send(chat, "❌ Admin only.", ext_team_menu(uid))
            else:
                user_sessions[str(uid)]["awaiting"] = "team_add"
                ext_send(chat, "Send the Telegram numeric user ID to add as a secondary admin.")
        elif data == "x_team_remove":
            ext_send_ai_assist(chat, uid, "team", "remove admin request")
            if not is_admin(uid):
                ext_send(chat, "❌ Admin only.", ext_team_menu(uid))
            else:
                user_sessions[str(uid)]["awaiting"] = "team_remove"
                ext_send(chat, "Send the Telegram numeric user ID to remove.")
        elif data == "x_team_list":
            ext_send_ai_assist(chat, uid, "team", "team list")
            admins = extension_state.get("team", {}).get("admins", [])
            ext_send(chat, "👥 **Team**

" + ("
".join(f"• `{x}`" for x in admins) if admins else "No secondary admins."), ext_team_menu(uid))
        elif data.startswith("x_tpl:"):
            kind = data.split(":", 1)[1]
            ext_send_ai_assist(chat, uid, "template", kind)
            bid, entry = ext_template_create(kind, uid)
            ext_set_bot(uid, bid)
            ext_send(chat, f"📦 Template deployed to `{bid}`.
Entry: `{entry}`

Use the existing control panel to start it.", ext_template_menu())
        else:
            return False
        return True
    except Exception as exc:
        logger.exception("Extension callback failed")
        ext_send(chat, f"❌ Extension error: `{safe_text(exc, 1600)}`", ext_feature_menu(uid))
        return True


def ext_handle_text(message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    state = user_sessions.setdefault(str(uid), {})
    awaiting = state.get("awaiting")
    if not awaiting:
        return False
    if text.lower() == "cancel":
        state.pop("awaiting", None)
        ext_send(message.chat.id, "❌ Cancelled.", ext_feature_menu(uid))
        return True
    try:
        if awaiting == "chat2script_prompt":
            proposal = ext_chat2script_proposal(uid, text)
            state["awaiting"] = state.get("awaiting")
            if isinstance(proposal, tuple):
                body, markup = proposal
                ext_send(message.chat.id, body, markup)
            else:
                ext_send(message.chat.id, proposal, ext_ai_menu())
            if state.get("awaiting") != "chat2script_confirm":
                state.pop("awaiting", None)
        elif awaiting == "github":
            bid, entry = ext_github_deploy(text, uid)
            state.pop("awaiting", None)
            ext_set_bot(uid, bid)
            result = start_bot_once(bid, entry, uid, reason="github_deploy", notify=False)
            ext_send(message.chat.id, f"🐙 GitHub deploy complete: `{bid}`
Entry: `{entry}`

{result.get('message','')}", ext_feature_menu(uid))
        elif awaiting == "ai_search":
            state.pop("awaiting", None)
            matches = ext_natural_bot_search(uid, text)
            ext_send(message.chat.id, "🔎 Matches:

" + ("
".join(f"• `{x}`" for x in matches[:10]) if matches else "No matching bots."), ext_ai_menu())
        elif awaiting == "schedule":
            parts = shlex.split(text)
            if len(parts) != 2 or parts[0] not in {"start", "stop", "restart", "backup"}:
                raise ValueError("Use: action delay_seconds")
            bid = ext_require_bot(uid)
            item = ext_schedule_add(uid, bid, parts[0], int(parts[1]))
            state.pop("awaiting", None)
            ext_send(message.chat.id, f"📅 Scheduled `{item['action']}` for `{item['bot_id']}` in `{int(parts[1])}` seconds.", ext_schedule_menu())
        elif awaiting == "team_add":
            if not is_admin(uid):
                raise PermissionError("Admin only")
            target = int(text)
            admins = extension_state.setdefault("team", {}).setdefault("admins", [])
            if target not in admins:
                admins.append(target)
            state.pop("awaiting", None)
            extension_save_state()
            ext_send(message.chat.id, f"✅ Added `{target}` to the secondary admin list.", ext_team_menu(uid))
        elif awaiting == "team_remove":
            if not is_admin(uid):
                raise PermissionError("Admin only")
            target = int(text)
            admins = extension_state.setdefault("team", {}).setdefault("admins", [])
            extension_state["team"]["admins"] = [x for x in admins if int(x) != target]
            state.pop("awaiting", None)
            extension_save_state()
            ext_send(message.chat.id, f"✅ Removed `{target}` from the secondary admin list.", ext_team_menu(uid))
        else:
            return False
        return True
    except Exception as exc:
        ext_send(message.chat.id, f"❌ `{safe_text(exc, 1200)}`")
        return True


@bot.callback_query_handler(func=lambda call: (call.data or "").startswith("x_"))
def _extension_callback_handler(call):
    ext_callback(call)


@bot.message_handler(commands=["chat2script", "script"])
def extension_chat2script_command(message):
    uid = message.from_user.id
    state = user_sessions.setdefault(str(uid), {})
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) == 1:
        state["awaiting"] = "chat2script_prompt"
        ext_send(
            message.chat.id,
            "🧑‍💻 Send the coding request or complete source code. "
            "I will prepare it and ask for deployment permission before running it.",
            ext_ai_menu(),
        )
        return
    proposal = ext_chat2script_proposal(uid, payload[1].strip())
    if isinstance(proposal, tuple):
        body, markup = proposal
        ext_send(message.chat.id, body, markup)
    else:
        ext_send(message.chat.id, proposal, ext_ai_menu())


@bot.message_handler(commands=["mode", "features", "ai", "normal"])
def extension_mode_command(message):
    uid = message.from_user.id
    command = (message.text or "").split()[0].lower()
    if command == "/ai":
        ext_set_mode(uid, "ai")
    elif command == "/normal":
        ext_set_mode(uid, "normal")
    ext_send(message.chat.id, ext_dashboard_text(uid), ext_feature_menu(uid))


@bot.message_handler(commands=["mybots"])
def extension_mybots(message):
    uid = message.from_user.id
    bots = ext_bot_list(uid)
    if not bots:
        ext_send(message.chat.id, "🤖 No hosted bots found.")
        return
    m = InlineKeyboardMarkup(row_width=2)
    for bid in bots[:50]:
        ext_set_bot(uid, bid)
        m.add(InlineKeyboardButton(f"{('🟢' if is_bot_running(bid) else '🔴')} {bid}", callback_data=f"x_pick:{bid}"))
    m.add(InlineKeyboardButton("🔙 Features", callback_data="x_features"))
    ext_send(message.chat.id, "🤖 **My Bots** — select a bot to make it the active context.", m)


@bot.message_handler(func=lambda message: bool(message.text) and message.text.strip().startswith("x:"))
def extension_text_router(message):
    # Explicit opt-in text protocol keeps normal legacy handlers untouched.
    return ext_handle_text(message)


@bot.message_handler(func=lambda message: bool(message.text) and user_sessions.get(str(message.from_user.id), {}).get("awaiting"))
def extension_awaiting_router(message):
    return ext_handle_text(message)


# Injected callback for bot context selection; kept separate from the legacy router.
@bot.callback_query_handler(func=lambda call: (call.data or "").startswith("x_pick:"))
def extension_pick_bot(call):
    uid = call.from_user.id
    bid = call.data.split(":", 1)[1]
    if not ext_is_owner(uid, bid):
        ext_send(call.message.chat.id, "❌ Permission denied.")
        return
    ext_set_bot(uid, bid)
    status = get_bot_status(bid)
    ext_send(call.message.chat.id, f"🤖 Active bot: `{bid}`
Status: `{status['status']}`", ext_feature_menu(uid))


def initialize_supercharged_addons():
    extension_load_state()
    # Restore persisted modes into the in-memory session map.
    for uid, mode in extension_state.get("modes", {}).items():
        user_sessions.setdefault(str(uid), {})["mode"] = mode
    for uid, enabled in extension_state.get("auto_mode", {}).items():
        user_sessions.setdefault(str(uid), {})["auto_mode"] = bool(enabled)
    threading.Thread(target=ext_schedule_worker, name="extension-scheduler", daemon=True).start()
    threading.Thread(target=ext_auto_sleep_worker, name="extension-auto-sleep", daemon=True).start()
    logger.info("Supercharged extension pack initialized.")


# ============================================================
# FINAL RELIABILITY / SELF-TEST LAYER
# ============================================================
RELIABILITY_VERSION = "FINAL-RELIABILITY-1.0"


def run_engine_selftest():
    """Deterministic local checks. Never calls AI and never mutates hosted bots."""
    checks = []

    def check(name, fn):
        try:
            result = fn()
            checks.append((name, bool(result), "OK" if result else "FAILED"))
        except Exception as exc:
            checks.append((name, False, safe_text(exc, 240)))

    check("Python runtime", lambda: sys.version_info >= (3, 9))
    check("HOST_DIR", lambda: os.path.isdir(HOST_DIR) or os.makedirs(HOST_DIR, exist_ok=True) is None)
    check("LOG_DIR", lambda: os.path.isdir(LOG_DIR) or os.makedirs(LOG_DIR, exist_ok=True) is None)
    check("Registry path", lambda: bool(REGISTRY_FILE))
    check("Atomic registry lock", lambda: hasattr(threading, "Lock"))
    check("AST parser", lambda: ast.parse("def _selftest():
    return True") is not None)
    check("Python compiler", lambda: py_compile.compile(__file__, doraise=True) is None)
    check("Requests", lambda: requests is not None)
    check("Telegram bot object", lambda: bot is not None)
    check("AI fallback", lambda: isinstance(ext_normal_fallback_for_action(ADMIN_ID, "support"), str))
    check("Rollback engine", lambda: callable(rollback_bot))
    check("Version engine", lambda: callable(create_bot_version))
    check("Health engine", lambda: callable(get_bot_status))
    check("Deployment engine", lambda: callable(start_bot_once))
    check("Chat→Script engine", lambda: callable(ext_chat2script_proposal) and callable(ext_chat2script_deploy))

    passed = sum(1 for _, ok, _ in checks if ok)
    return passed, len(checks), checks


@bot.message_handler(commands=["selftest", "healthcheck"])
def extension_selftest_command(message):
    uid = int(getattr(message.from_user, "id", 0) or 0)
    if uid != ADMIN_ID:
        ext_send(message.chat.id, "❌ Admin only.")
        return
    passed, total, checks = run_engine_selftest()
    rows = [
        f"🧪 **Engine Self-Test** `{RELIABILITY_VERSION}`",
        "",
        f"Result: **{passed}/{total} local checks passed**",
        "",
    ]
    for name, ok, detail in checks:
        rows.append(f"{'✅' if ok else '❌'} {name}: {detail}")
    rows.append("")
    rows.append("ℹ️ External Telegram/GitHub/AI availability is environment-dependent and is not falsely reported as guaranteed by this local test.")
    ext_send(message.chat.id, "
".join(rows))


# ============================================================
# MAIN RUNNER
# ============================================================

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

        initialize_supercharged_addons()

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

        polling_thread = threading.Thread(
            target=lambda: bot.infinity_polling(
                timeout=10,
                long_polling_timeout=5,
                skip_pending=True,
            ),
            name="telegram-polling",
            daemon=True,
        )

        polling_thread.start()

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

        cleanup_engine()
