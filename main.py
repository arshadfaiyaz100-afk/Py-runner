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
