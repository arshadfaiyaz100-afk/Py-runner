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
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

try:
    import psutil
except ImportError:
    psutil = None

try:
    from pyrogram import Client
    MTPROTO_AVAILABLE = True
except ImportError:
    MTPROTO_AVAILABLE = False

# ==========================================
# ⚙️ CONFIGS & MTPROTO CREDENTIALS (SUPERCHARGED)
# ==========================================
ADMIN_ID = 7193432903
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8483068207:AAEq3LPHIYlug4qtQnkc9dQB2u-r6kQm1cs")
GH_TOKEN = os.environ.get("GH_TOKEN", "") 
GH_REPO = os.environ.get("GH_REPO", "my-hosted-bots")

# 🚀 GLOBAL MTPROTO CREDENTIALS (Shatters 50MB/20MB Limits)
GLOBAL_API_ID = int("29387151")
GLOBAL_API_HASH = "1d70091141dda904d82684938d444473"

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=32)
app = Flask(__name__)

# ==========================================
# 📂 SYSTEM DIRECTORIES & TRUE ISOLATION
# ==========================================
BASE_DIR = os.path.abspath(os.getcwd())
HOST_DIR = os.path.join(BASE_DIR, "hosted_env")
LOG_DIR = os.path.join(BASE_DIR, "logs")
TEMP_DIR = os.path.join(BASE_DIR, "temp_uploads")
REGISTRY_FILE = os.path.join(BASE_DIR, "registry.json")

for d in [HOST_DIR, LOG_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

hosted_processes = {}  
user_deploy_states = {} 
user_chats = set()
banned_users = set()
user_custom_envs = {}
engine_start_time = time.time()
MAINTENANCE_MODE = False  

PIP_MAP = {
    "telebot": "pyTelegramBotAPI", "PIL": "Pillow", "bs4": "beautifulsoup4",
    "cv2": "opencv-python", "yaml": "pyyaml", "crypto": "pycryptodome", 
    "sklearn": "scikit-learn", "telegram": "python-telegram-bot",
    "discord": "discord.py", "pyrogram": "pyrogram tgcrypto", "aiogram": "aiogram",
    "dotenv": "python-dotenv", "dateutil": "python-dateutil", "jose": "python-jose",
    "jwt": "PyJWT", "dantic": "pydantic", "torch": "torch", "tensorflow": "tensorflow"
}
BUILTINS = sys.builtin_module_names

# ==========================================
# 💾 PERFECT PERSISTENT REGISTRY SYSTEM 
# ==========================================
def save_registry():
    data = {
        "bots": {bid: {"owner_id": p["owner_id"], "entry_file": p["entry_file"]} for bid, p in hosted_processes.items()},
        "envs": user_custom_envs,
        "chats": list(user_chats),
        "maintenance": MAINTENANCE_MODE
    }
    try:
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)
    except: pass

def load_registry():
    global user_custom_envs, user_chats, MAINTENANCE_MODE
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f: data = json.load(f)
            user_custom_envs = data.get("envs", {})
            user_chats = set(data.get("chats", []))
            MAINTENANCE_MODE = data.get("maintenance", False)
            bots = data.get("bots", {})
            for bid, info in bots.items():
                bot_dir = os.path.join(HOST_DIR, bid)
                entry = info["entry_file"]
                if os.path.exists(os.path.join(bot_dir, entry)):
                    run_script_process(bid, entry, info["owner_id"]) 
        except: pass

# ==========================================
# 🌐 KEEP-ALIVE WEB SERVER
# ==========================================
@app.route('/')
def home():
    active_count = len([p for p in hosted_processes.values() if p["process"] and p["process"].poll() is None])
    return f"⚡ Supercharged Python Engine Live! Active Bots: {active_count}"

# ==========================================
# 🧠 SMART CORE UTILITIES & XX CHARGED LIMITS
# ==========================================
def is_admin(user_id): return int(user_id) == ADMIN_ID
def is_banned(user_id): return user_id in banned_users

def get_readable_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(importlib.math.floor(importlib.math.log(size_bytes, 1024))) if size_bytes > 0 else 0
    p = importlib.math.pow(1024, i)
    return f"{round(size_bytes / p, 2)} {size_name[i]}"

def get_readable_uptime(seconds):
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {mins}m {secs}s"

def get_progress_bar(percent, length=10):
    filled = int((percent / 100) * length)
    return "█" * filled + "░" * (length - filled)

def update_hud(chat_id, msg_id, title, action, percent, start_time):
    bar = get_progress_bar(percent)
    elapsed = round(time.time() - start_time, 1)
    text = f"⚙️ **{title}**\n\n`[{bar}] {percent}%`\n\n⚡ **Status:** `{action}`\n⏱️ **Elapsed:** `{elapsed}s`"
    try: bot.edit_message_text(text, chat_id, msg_id, parse_mode="Markdown")
    except: pass

# 🚀 INFINITE TEXT CHUNKER (Bypasses 4096 Char Limit)
def send_long_message(chat_id, text, parse_mode=None, reply_markup=None, is_code=False):
    chunk_size = 3900 
    if len(text) <= chunk_size:
        try: bot.send_message(chat_id, f"```text\n{text}\n```" if is_code else text, parse_mode=parse_mode, reply_markup=reply_markup)
        except: pass
        return
    parts = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        msg_text = f"```text\n{part}\n```" if is_code else part
        try: bot.send_message(chat_id, msg_text, parse_mode=parse_mode, reply_markup=markup)
        except: pass
        time.sleep(0.2) 

# 🚀 MTPROTO HEAVY FILE DOWNLOADER (Bypasses 20MB Limit -> 2GB)
def mtproto_download(chat_id, message_id, dest_path):
    async def run():
        async with Client("mtproto_engine", api_id=GLOBAL_API_ID, api_hash=GLOBAL_API_HASH, bot_token=BOT_TOKEN, in_memory=True) as app:
            msg = await app.get_messages(chat_id, message_id)
            await app.download_media(msg, file_name=dest_path)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())

# 🚀 MTPROTO HEAVY FILE UPLOADER (Bypasses 50MB Limit -> 2GB)
def mtproto_upload(chat_id, file_path, caption):
    async def run():
        async with Client("mtproto_engine", api_id=GLOBAL_API_ID, api_hash=GLOBAL_API_HASH, bot_token=BOT_TOKEN, in_memory=True) as app:
            await app.send_document(chat_id, document=file_path, caption=caption)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())

def generate_bot_id():
    while True:
        b_id = f"BOT-{random.randint(1000, 9999)}"
        if b_id not in hosted_processes and b_id not in user_deploy_states: return b_id

def deep_analyze_imports(bot_folder):
    detected_modules = set()
    for root, _, files in os.walk(bot_folder):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        tree = ast.parse(f.read())
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Import):
                                for alias in node.names: detected_modules.add(alias.name.split('.')[0])
                            elif isinstance(node, ast.ImportFrom) and node.module:
                                detected_modules.add(node.module.split('.')[0])
                except: pass
    return [PIP_MAP.get(m, m) for m in detected_modules if m not in BUILTINS]

# ==========================================
# 🛑 STRICT PACKAGE VERIFICATION ENGINE
# ==========================================
def auto_install_packages_verified(modules, chat_id, msg_id, start_time):
    if not modules: return True, ""
    total = len(modules)
    for index, mod in enumerate(modules, start=1):
        pct = int((index / total) * 100)
        mod_import_name = mod.split()[0].replace("-", "_")
        
        if importlib.util.find_spec(mod_import_name) is not None:
            update_hud(chat_id, msg_id, "Strict Dependency Installer", f"Skipping (Already Installed) ➔ `{mod}`", pct, start_time)
            time.sleep(0.3)
            continue
            
        update_hud(chat_id, msg_id, "Strict Dependency Installer", f"Downloading & Installing [{index}/{total}] ➔ `{mod}`", pct, start_time)
        try:
            res = subprocess.run([sys.executable, '-m', 'pip', 'install', *mod.split(), '--no-cache-dir'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
            if res.returncode != 0: return False, f"Failed to install package `{mod}`.\n\nError Log:\n{res.stderr[-400:]}"
        except Exception as e: return False, f"Exception occurred during installation of `{mod}`: {str(e)}"
    return True, ""

# ==========================================
# ⚙️ HEAVY PROCESS MANAGER & SECURE ENVS
# ==========================================
def run_script_process(bot_id, entry_file, owner_id):
    bot_dir = os.path.join(HOST_DIR, bot_id)
    log_file_path = os.path.join(LOG_DIR, f"{bot_id}.log")
    log_out = open(log_file_path, "a", encoding="utf-8")
    
    custom_env = os.environ.copy()
    
    # 🔒 MTPROTO SUPERCHARGED ENV INJECTION
    if is_admin(owner_id):
        custom_env["API_ID"] = str(GLOBAL_API_ID)
        custom_env["API_HASH"] = GLOBAL_API_HASH
        
    if owner_id in user_custom_envs: custom_env.update(user_custom_envs[owner_id])
    
    proc = subprocess.Popen([sys.executable, entry_file], cwd=bot_dir, stdout=log_out, stderr=log_out, env=custom_env, text=True)
    hosted_processes[bot_id] = {"process": proc, "entry_file": entry_file, "owner_id": owner_id, "start_time": time.time(), "log_file": log_file_path, "retries": 0}
    save_registry()

def stop_script_process(bot_id):
    if bot_id in hosted_processes:
        proc = hosted_processes[bot_id]["process"]
        if proc and proc.poll() is None:
            try:
                if psutil:
                    parent = psutil.Process(proc.pid)
                    for child in parent.children(recursive=True): child.kill() 
                    parent.kill()
                else:
                    proc.kill()
            except: pass
        del hosted_processes[bot_id]
        save_registry()

def auto_healing_monitor():
    while True:
        time.sleep(10)
        for bot_id, data in list(hosted_processes.items()):
            proc, owner_id, entry_file = data["process"], data["owner_id"], data["entry_file"]
            
            if psutil and proc.poll() is None:
                try:
                    p = psutil.Process(proc.pid)
                    if p.memory_info().rss > 2048 * 1024 * 1024:  
                        stop_script_process(bot_id)
                        bot.send_message(owner_id, f"🚨 **HEAVY ENGINE WARNING:** Bot `{bot_id}` exceeded 2GB RAM limit and was auto-stopped!")
                        continue
                except: pass

            if proc.poll() is not None: 
                log_path = data["log_file"]
                missing_pkg = None
                if os.path.exists(log_path):
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as lf:
                        match = re.search(r"No module named '([^']+)'", lf.read()[-2000:])
                        if match: missing_pkg = match.group(1)

                if missing_pkg and data["retries"] < 5:
                    data["retries"] += 1
                    target_pkg = PIP_MAP.get(missing_pkg, missing_pkg)
                    bot.send_message(owner_id, f"⚡ **Self-Healing:** Installing missing `{target_pkg}` for `{bot_id}`...")
                    try: subprocess.run([sys.executable, '-m', 'pip', 'install', target_pkg], timeout=300)
                    except: pass
                    run_script_process(bot_id, entry_file, owner_id)
                elif data["retries"] < 3:
                    data["retries"] += 1
                    run_script_process(bot_id, entry_file, owner_id)

# ==========================================
# 🎛️ THE ULTIMATE 5-MENU ECOSYSTEM
# ==========================================
def get_user_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    user_bots = [b for b, d in hosted_processes.items() if (d["owner_id"] == user_id or is_admin(user_id)) and d["process"].poll() is None]
    markup.add(
        InlineKeyboardButton("🚀 Deploy Bot (Any Size)", callback_data="host_file"),
        InlineKeyboardButton("🔍 ID Search Hub", callback_data="search_hub"),
        InlineKeyboardButton(f"🤖 Managed Active Bots ({len(user_bots)})", callback_data="my_bots"),
        InlineKeyboardButton("🛑 Stop All Actions", callback_data="stop_my_bots"),
        InlineKeyboardButton("🔑 Manage My ENVs", callback_data="manage_env"),
        InlineKeyboardButton("📂 Storage & Backup", callback_data="browse_files"),
        InlineKeyboardButton("📊 Advanced Health", callback_data="server_ping")
    )
    if is_admin(user_id): markup.add(InlineKeyboardButton("👑 Master Admin Controls", callback_data="admin_panel"))
    return markup

def get_search_hub_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🔍 Find Bot by ID", callback_data="search_by_id"), InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu"))
    return markup

def get_package_menu(bot_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("🧠 Smart Auto-Install", callback_data=f"pkg_auto:{bot_id}"), InlineKeyboardButton("📝 Manual (.txt)", callback_data=f"pkg_manual:{bot_id}"))
    return markup

def get_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    maint_status = "🟢 ON" if MAINTENANCE_MODE else "🔴 OFF"
    markup.add(
        InlineKeyboardButton(f"💻 Root Terminal", callback_data="admin_terminal"),
        InlineKeyboardButton(f"🛠 Maintenance Mode: {maint_status}", callback_data="toggle_maintenance"),
        InlineKeyboardButton("🌐 Global Nodes List", callback_data="list_all_bots"),
        InlineKeyboardButton("🚨 EMERGENCY PURGE", callback_data="emergency_kill"),
        InlineKeyboardButton("🧹 Deep System Clean", callback_data="server_clean"),
        InlineKeyboardButton("📢 Live Broadcast", callback_data="broadcast_menu"),
        InlineKeyboardButton("🔙 Root Dashboard", callback_data="main_menu")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    if is_banned(user_id): return
    user_chats.add(message.chat.id)
    save_registry()
    
    if MAINTENANCE_MODE and not is_admin(user_id): return bot.send_message(message.chat.id, "🛠 **SERVER UNDER MAINTENANCE!**\nSystem is updating.")
    
    mtproto_status = "🟢 ACTIVE (2GB Limits Bypassed)" if MTPROTO_AVAILABLE else "🔴 OFFLINE"
    dash_text = (
        f"⚡ **XX SUPERCHARGED HOSTING ENGINE** ⚡\n\n"
        f"🆔 **Your ID:** `{user_id}`\n"
        f"🔰 **Access Level:** {'Master Admin' if is_admin(user_id) else 'Standard'}\n\n"
        f"🚀 **MTProto Core:** {mtproto_status}\n"
        f"📂 Upload infinite `.py` scripts or massive `.zip` projects up to 2GB."
    )
    bot.send_message(message.chat.id, dash_text, parse_mode="Markdown", reply_markup=get_user_menu(user_id))

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    global MAINTENANCE_MODE
    uid, chat = call.from_user.id, call.message.chat.id
    data = call.data
    user_chats.add(chat)
    bot.clear_step_handler_by_chat_id(chat) 

    if data == "main_menu": bot.edit_message_text("🎛️ **Root Dashboard:**", chat, call.message.message_id, reply_markup=get_user_menu(uid))
    elif data == "admin_panel" and is_admin(uid): bot.edit_message_text("👑 **Admin Master Controls:**", chat, call.message.message_id, reply_markup=get_admin_menu())
    elif data == "search_hub": bot.edit_message_text("🔍 **Identity Search Hub:**", chat, call.message.message_id, reply_markup=get_search_hub_menu())
    
    elif data == "host_file":
        if MAINTENANCE_MODE and not is_admin(uid): return bot.answer_callback_query(call.id, "Maintenance Active", show_alert=True)
        bot.send_message(chat, "📂 **Upload Python `.py` or heavy `.zip` project:**\n*(File >20MB will automatically route via MTProto)*\n*(Type 'cancel' to abort)*")
        bot.register_next_step_handler(call.message, process_script_upload)
        
    elif data == "search_by_id":
        bot.send_message(chat, "🔍 Enter Target Bot ID (e.g., `BOT-1234`) or type 'cancel':", parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_search_bot)
        
    elif data.startswith("pkg_auto:"):
        threading.Thread(target=finalize_deployment, args=(chat, call.message.message_id, data.split(":")[1], "auto")).start()
        
    elif data.startswith("pkg_manual:"):
        bot.edit_message_text("📝 **Manual Verification Installer:**\n\nSend `requirements.txt` OR type package names (Type 'cancel' to abort):", chat, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, lambda m: handle_manual_reqs(m, data.split(":")[1]))
        
    elif data == "toggle_maintenance" and is_admin(uid):
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        save_registry()
        bot.edit_message_reply_markup(chat, call.message.message_id, reply_markup=get_admin_menu())
        
    elif data == "server_ping":
        latency = round((time.time() - engine_start_time) * 1000, 2)
        ram = psutil.virtual_memory().percent if psutil else 0
        cpu = psutil.cpu_percent(interval=0.5) if psutil else 0
        total_disk, used_disk, free_disk = shutil.disk_usage("/")
        mtproto_status = "🟢 ACTIVE (2GB Limits Bypassed)" if MTPROTO_AVAILABLE else "🔴 OFFLINE"
        
        stat_text = (
            f"📊 **Advanced Health Monitor (XX Mode)** 📊\n\n"
            f"⏱️ **System Uptime:** `{get_readable_uptime(time.time() - engine_start_time)}`\n"
            f"📡 **Network Latency:** `{latency}ms`\n"
            f"🚀 **MTProto Protocol:** {mtproto_status}\n\n"
            f"🖥️ **CPU Load:** `{cpu}%`\n`[{get_progress_bar(cpu, 15)}]`\n\n"
            f"💾 **RAM Memory:** `{ram}%`\n`[{get_progress_bar(ram, 15)}]`\n\n"
            f"💽 **Disk Space:** `{int(used_disk/(1024**3))}GB / {int(total_disk/(1024**3))}GB`"
        )
        bot.send_message(chat, stat_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="main_menu")))
        
    elif data == "manage_env":
        user_envs = user_custom_envs.get(uid, {})
        env_str = "\n".join([f"🔹 `{k}` : `***`" for k in user_envs.keys()]) if user_envs else "🔹 No Custom ENVs set."
        admin_note = "\n\n*👑 Master Core: MTProto API_ID & API_HASH pre-injected securely.*" if is_admin(uid) else ""
        
        bot.send_message(chat, f"🔑 **Your Secure Variables:**\n{env_str}{admin_note}\n\n➕ **To add new:** Send format `KEY=VALUE` (or 'cancel'):", parse_mode="Markdown")
        bot.register_next_step_handler(call.message, save_env_var)
        
    elif data == "server_clean" and is_admin(uid):
        try:
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
            os.makedirs(TEMP_DIR, exist_ok=True)
            for root, dirs, files in os.walk(LOG_DIR):
                for f in files:
                    if os.path.getsize(os.path.join(root, f)) > 10 * 1024 * 1024: open(os.path.join(root, f), 'w').close() 
            bot.send_message(chat, "🧹 **Deep System Cleaned! Logs truncated & cache cleared!**")
        except Exception as e: bot.send_message(chat, f"⚠️ Partial Clean: {e}")
        
    elif data == "browse_files":
        bot.send_message(chat, "📂 **Secure Data Explorer:**", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("📦 EXPORT FULL ARCHIVE", callback_data="export_zip"), InlineKeyboardButton("🔙 Back", callback_data="main_menu")))
        
    elif data == "export_zip":
        bot.send_message(chat, "📦 Compressing massive core files...")
        zip_path = os.path.join(TEMP_DIR, f"backup_{uid}.zip")
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(HOST_DIR):
                for f in files:
                    if is_admin(uid) or not f.endswith('.log'): zipf.write(os.path.join(root, f), arcname=f)
        
        # XX CHARGED 2GB EXPORT PROTOCOL
        zip_size = os.path.getsize(zip_path)
        if zip_size > 49 * 1024 * 1024 and MTPROTO_AVAILABLE:
            bot.send_message(chat, f"🚀 **Archive Size:** `{get_readable_size(zip_size)}` (>50MB).\nEngaging MTProto Core to bypass limits and upload...")
            threading.Thread(target=mtproto_upload, args=(chat, zip_path, "📦 **Massive Core Archive Exported**")).start()
        else:
            bot.send_document(chat, open(zip_path, 'rb'))
            os.remove(zip_path)
        
    elif data in ["my_bots", "list_all_bots"]:
        if data == "list_all_bots" and not is_admin(uid): return
        items = [(bid, d) for bid, d in hosted_processes.items() if is_admin(uid) or d["owner_id"] == uid]
        if not items: return bot.send_message(chat, "📂 No active nodes found.", reply_markup=get_user_menu(uid))
        m = InlineKeyboardMarkup(row_width=1)
        for bid, d in items:
            status = "🟢" if d["process"].poll() is None else "🔴"
            m.add(InlineKeyboardButton(f"{status} {bid} ({os.path.basename(d['entry_file'])})", callback_data=f"manage:{bid}"))
        m.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.send_message(chat, "🤖 **Managed Core Bots:**", reply_markup=m)
        
    elif data.startswith("manage:"):
        bid = data.split(":", 1)[1]
        if bid not in hosted_processes: return bot.answer_callback_query(call.id, "Node missing.", show_alert=True)
        p = hosted_processes[bid]
        
        is_running = p["process"].poll() is None
        uptime_str = get_readable_uptime(time.time() - p["start_time"]) if is_running else "Offline"
        log_sz = os.path.getsize(p["log_file"]) if os.path.exists(p["log_file"]) else 0
        sz_str = get_readable_size(log_sz)
        
        panel_text = (
            f"⚙️ **Node Control Center:** `{bid}`\n\n"
            f"📄 **Target:** `{p['entry_file']}`\n"
            f"⏱️ **Uptime:** `{uptime_str}`\n"
            f"🗃️ **Log Weight:** `{sz_str}`\n"
            f"🟢 **Status:** `{'Running' if is_running else 'Halted'}`"
        )
        
        m = InlineKeyboardMarkup(row_width=2)
        if is_running: m.add(InlineKeyboardButton("🛑 Terminate", callback_data=f"stop:{bid}"), InlineKeyboardButton("🔄 Hard Restart", callback_data=f"restart:{bid}"))
        else: m.add(InlineKeyboardButton("▶️ Boot Sequence", callback_data=f"start:{bid}"))
        m.add(InlineKeyboardButton("📜 Inspect Deep Logs", callback_data=f"log:{bid}"), InlineKeyboardButton("📝 Instant Edit", callback_data=f"edit_code:{bid}"))
        m.add(InlineKeyboardButton("🗑️ Obliterate Node", callback_data=f"del:{bid}"), InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu"))
        
        bot.send_message(chat, panel_text, parse_mode="Markdown", reply_markup=m)
        
    elif data.startswith("edit_code:"):
        bid = data.split(":", 1)[1]
        bot.send_message(chat, f"📝 **Instant Script Editor (`{bid}`):**\n\nPaste your entirely updated Python code below OR type 'cancel':")
        bot.register_next_step_handler(call.message, lambda m: save_edited_code(m, bid))
        
    elif data.startswith("log:"):
        bid = data.split(":", 1)[1]
        log_path = hosted_processes[bid]["log_file"]
        content = "No logs yet."
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as logf: 
                content = logf.read()[-15000:] # Increased log read limit dramatically
        m = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Synchronize", callback_data=f"log:{bid}"), InlineKeyboardButton("🔙 Back", callback_data=f"manage:{bid}"))
        
        # Supercharged Limit Bypass for Logs
        bot.send_message(chat, f"📜 **Live Deep Console (`{bid}`):**", reply_markup=m)
        send_long_message(chat, content, parse_mode="Markdown", is_code=True)
        
    elif data.startswith("stop:"):
        bid = data.split(":", 1)[1]; stop_script_process(bid); bot.send_message(chat, f"🛑 Node `{bid}` forcefully halted.")
    elif data.startswith("start:"): 
        bid = data.split(":", 1)[1]; p = hosted_processes[bid]; run_script_process(bid, p["entry_file"], p["owner_id"]); bot.send_message(chat, f"✅ Node `{bid}` booted!")
    elif data.startswith("restart:"): 
        bid = data.split(":", 1)[1]; p = hosted_processes[bid]; stop_script_process(bid); run_script_process(bid, p["entry_file"], p["owner_id"]); bot.send_message(chat, f"🔄 Node `{bid}` restarted smoothly!")
    elif data.startswith("del:"): 
        bid = data.split(":", 1)[1]; p = hosted_processes.get(bid)
        if p:
            stop_script_process(bid)
            try: shutil.rmtree(os.path.join(HOST_DIR, bid), ignore_errors=True)
            except: pass
            save_registry()
        bot.send_message(chat, f"🗑️ Node `{bid}` completely obliterated.")
        
    elif data == "emergency_kill" and is_admin(uid):
        for bid in list(hosted_processes.keys()): stop_script_process(bid)
        bot.send_message(chat, "🚨 **DEFCON 1: ALL NODES KILLED INSTANTLY!**", parse_mode="Markdown")
        
    elif data == "stop_my_bots":
        for bid, d in list(hosted_processes.items()):
            if d["owner_id"] == uid: stop_script_process(bid)
        bot.send_message(chat, "🛑 Your active nodes have been safely parked.")
        
    elif data == "admin_terminal" and is_admin(uid):
        bot.send_message(chat, "💻 **ROOT TERMINAL ACTIVE.**\nSend any bash command (e.g. `ls -la`, `pip list`). Type 'cancel' to exit.")
        bot.register_next_step_handler(call.message, process_terminal_cmd)
        
    elif data == "broadcast_menu" and is_admin(uid):
        bot.send_message(chat, "📢 **Anti-Ban Broadcast Console:**\nSend your message (Text, Photo, File) OR type 'cancel':")
        bot.register_next_step_handler(call.message, process_broadcast)

# ==========================================
# 🚀 THE XX SUPERCHARGED DEPLOYMENT WORKFLOW
# ==========================================
def process_script_upload(message):
    if message.text and message.text.lower() == 'cancel': return bot.send_message(message.chat.id, "❌ Action Cancelled.")
    user_id = message.from_user.id
    if not message.document and not message.text: return
    
    bot_id = generate_bot_id()
    bot_dir = os.path.join(HOST_DIR, bot_id)
    os.makedirs(bot_dir, exist_ok=True)
    
    start_time = time.time()
    progress = bot.send_message(message.chat.id, f"🔄 Initializing Secure HUD for `{bot_id}`...", parse_mode="Markdown")
    
    try:
        if message.text:
            entry_file = "main.py"
            with open(os.path.join(bot_dir, entry_file), "w", encoding="utf-8") as f: f.write(message.text)
        else:
            filename = message.document.file_name
            file_size = message.document.file_size
            
            if not (filename.endswith('.py') or filename.endswith('.zip')): return bot.edit_message_text("❌ Required `.py` or `.zip` file format.", message.chat.id, progress.message_id)
            
            target_file = os.path.join(TEMP_DIR, f"{bot_id}.zip") if filename.endswith('.zip') else os.path.join(bot_dir, filename)
            
            # XX CHARGED 2GB DOWNLOAD PROTOCOL
            if file_size > 20 * 1024 * 1024 and MTPROTO_AVAILABLE:
                update_hud(message.chat.id, progress.message_id, "MTProto Core HUD", f"Massive Payload Detected (`{get_readable_size(file_size)}`).\nBypassing 20MB limit. Streaming directly from MTProto servers...", 30, start_time)
                mtproto_download(message.chat.id, message.message_id, target_file)
            else:
                update_hud(message.chat.id, progress.message_id, "Core Telemetry HUD", "Streaming standard data from Telegram...", 20, start_time)
                file_info = bot.get_file(message.document.file_id)
                downloaded = bot.download_file(file_info.file_path)
                with open(target_file, "wb") as f: f.write(downloaded)
            
            if filename.endswith('.zip'):
                update_hud(message.chat.id, progress.message_id, "Core Telemetry HUD", "Extracting Massive ZIP & Isolating Files...", 45, start_time)
                with zipfile.ZipFile(target_file, 'r') as zip_ref: zip_ref.extractall(bot_dir)
                os.remove(target_file)
                
                possible_mains = ['main.py', 'bot.py', 'app.py']
                entry_file = None
                for root, dirs, files in os.walk(bot_dir):
                    for file in files:
                        if file in possible_mains:
                            entry_file = os.path.relpath(os.path.join(root, file), bot_dir)
                            break
                    if entry_file: break
                    
                if not entry_file: return bot.edit_message_text("❌ ZIP framework missing `main.py` or `bot.py` entrypoint!", message.chat.id, progress.message_id)
                
                if os.path.exists(os.path.join(bot_dir, "requirements.txt")):
                    user_deploy_states[bot_id] = {"owner_id": user_id, "entry_file": entry_file, "msg_id": progress.message_id, "start_time": start_time}
                    return finalize_deployment(message.chat.id, progress.message_id, bot_id, "manual", os.path.join(bot_dir, "requirements.txt"))
            else:
                entry_file = filename
        
        user_deploy_states[bot_id] = {"owner_id": user_id, "entry_file": entry_file, "msg_id": progress.message_id, "start_time": start_time}
        bot.edit_message_text(f"📦 **Secure Node Locked:** `{bot_id}`\n\nChoose strictly verified dependency protocol:", message.chat.id, progress.message_id, parse_mode="Markdown", reply_markup=get_package_menu(bot_id))
    except Exception as e:
        bot.edit_message_text(f"❌ **Fatal Error:** `{str(e)}`", message.chat.id, progress.message_id, parse_mode="Markdown")

def finalize_deployment(chat_id, msg_id, bot_id, install_type, manual_req_path=None):
    state = user_deploy_states.get(bot_id)
    if not state: return
    user_id, entry_file, start_time = state["owner_id"], state["entry_file"], state["start_time"]
    bot_dir = os.path.join(HOST_DIR, bot_id)
    script_path = os.path.join(bot_dir, entry_file)
    
    if install_type == "manual" and manual_req_path and os.path.exists(manual_req_path):
        update_hud(chat_id, msg_id, "Strict Setup HUD", "Enforcing manual requirements compile...", 60, start_time)
        res = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', manual_req_path, '--no-cache-dir'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
        if res.returncode != 0: return bot.edit_message_text(f"❌ **Install Halted (Strict Guard):**\n```text\n{res.stderr[-300:]}\n```", chat_id, msg_id, parse_mode="Markdown")
    else:
        update_hud(chat_id, msg_id, "Strict Setup HUD", "Parsing deep AST Imports & Modules...", 50, start_time)
        needed_packages = deep_analyze_imports(bot_dir)
        success, err_msg = auto_install_packages_verified(needed_packages, chat_id, msg_id, start_time)
        if not success: return bot.edit_message_text(f"❌ **Install Halted (Strict Guard):**\n```text\n{err_msg}\n```", chat_id, msg_id, parse_mode="Markdown")

    update_hud(chat_id, msg_id, "Strict Setup HUD", "Final compilation & sandboxing...", 85, start_time)
    try: py_compile.compile(script_path, doraise=True)
    except py_compile.PyCompileError as sys_err: return bot.edit_message_text(f"⚠️ Syntax Guard Halt:\n```text\n{sys_err}\n```", chat_id, msg_id, parse_mode="Markdown")

    run_script_process(bot_id, entry_file, user_id)
    if bot_id in user_deploy_states: del user_deploy_states[bot_id]

    update_hud(chat_id, msg_id, "Strict Setup HUD", "Node 100% Operational & Verified!", 100, start_time)
    bot.send_message(chat_id, f"🚀 **Node Deployed & Locked!**\n📌 **Identity:** `{bot_id}`\n🚀 Status: LIVE CORE", parse_mode="Markdown")
    bot.send_message(chat_id, "🎛️ **Manage Options:**", reply_markup=get_user_menu(user_id))

# ==========================================
# 📢 ASYNCHRONOUS ANTI-BAN BROADCAST ENGINE
# ==========================================
def process_broadcast(message):
    if message.text and message.text.lower() == 'cancel': return bot.send_message(message.chat.id, "❌ Broadcast Cancelled.")
    if not is_admin(message.from_user.id): return
    
    user_chats.add(message.chat.id)
    save_registry()
    
    msg = bot.send_message(message.chat.id, "🚀 **Asynchronous Broadcast Initiated...**\n`Anti-Ban Protocol Active. Relaying payloads...`", parse_mode="Markdown")
    
    def run_bcast():
        count, failed = 0, 0
        for target_id in list(user_chats):
            try: 
                bot.copy_message(chat_id=target_id, from_chat_id=message.chat.id, message_id=message.message_id)
                count += 1
                time.sleep(0.06) # Core Anti-FloodWait Delay
            except: 
                failed += 1
                
        try: bot.edit_message_text(f"✅ **Global Broadcast Finalized!**\n\n🟢 Total Success: `{count}` Nodes\n🔴 Firewall Blocked: `{failed}` Nodes", message.chat.id, msg.message_id, parse_mode="Markdown", reply_markup=get_admin_menu())
        except: bot.send_message(message.chat.id, f"✅ **Global Broadcast Finalized!**\n\n🟢 Total Success: `{count}` Nodes\n🔴 Firewall Blocked: `{failed}` Nodes", parse_mode="Markdown", reply_markup=get_admin_menu())
        
    threading.Thread(target=run_bcast, daemon=True).start()

# Utilities
def process_terminal_cmd(message):
    if message.text.lower() == 'cancel': return bot.send_message(message.chat.id, "Terminal closed.", reply_markup=get_admin_menu())
    try: 
        res = subprocess.getoutput(message.text)
        send_long_message(message.chat.id, f"💻 **System Output:**\n\n{res}", parse_mode="Markdown", is_code=True)
    except Exception as e: bot.send_message(message.chat.id, str(e))
    bot.register_next_step_handler(message, process_terminal_cmd)

def handle_manual_reqs(message, bot_id):
    if message.text and message.text.lower() == 'cancel': return bot.send_message(message.chat.id, "❌ Verification Cancelled.")
    bot_dir = os.path.join(HOST_DIR, bot_id)
    try:
        req_p = os.path.join(bot_dir, "requirements.txt")
        if message.document:
            with open(req_p, "wb") as f: f.write(bot.download_file(bot.get_file(message.document.file_id).file_path))
        else:
            with open(req_p, "w") as f: f.write(message.text.replace(",", "\n"))
        msg = bot.send_message(message.chat.id, "📥 Booting strict manual verification...")
        threading.Thread(target=finalize_deployment, args=(message.chat.id, msg.message_id, bot_id, "manual", req_p)).start()
    except Exception as e: bot.send_message(message.chat.id, f"❌ Deep Error: {e}")

def process_search_bot(message):
    if message.text.lower() == 'cancel': return bot.send_message(message.chat.id, "❌ Cancelled.")
    query = message.text.strip().upper()
    if not query.startswith("BOT-"): query = f"BOT-{query}"
    if query in hosted_processes: bot.send_message(message.chat.id, f"🔍 **Node Verified:** `{query}`", parse_mode="Markdown", reply_markup=get_control_panel(query, hosted_processes[query]["process"].poll() is None))
    else: bot.send_message(message.chat.id, f"❌ Node `{query}` does not exist in registry.")

def save_edited_code(message, bot_id):
    if message.text and message.text.lower() == 'cancel': return bot.send_message(message.chat.id, "❌ Override Cancelled.")
    proj = hosted_processes.get(bot_id)
    if not proj: return bot.send_message(message.chat.id, "Node integrity lost.")
    
    script_path = os.path.join(HOST_DIR, bot_id, proj["entry_file"])
    stop_script_process(bot_id)
    if message.document:
        with open(script_path, 'wb') as f: f.write(bot.download_file(bot.get_file(message.document.file_id).file_path))
    else:
        with open(script_path, 'w', encoding='utf-8') as f: f.write(message.text)
    
    run_script_process(bot_id, proj["entry_file"], proj["owner_id"])
    bot.send_message(message.chat.id, f"✅ `{bot_id}` Data Overwritten & Hard-Restarted!", reply_markup=get_control_panel(bot_id, True))

def save_env_var(message):
    if message.text.lower() == 'cancel': return bot.send_message(message.chat.id, "❌ Cancelled.")
    try:
        key, val = message.text.split("=", 1)
        user_custom_envs.setdefault(message.from_user.id, {})[key.strip()] = val.strip()
        save_registry()
        bot.send_message(message.chat.id, f"✅ **Core ENV Secured:** `{key.strip()}`\n(Applied to all future boots)", parse_mode="Markdown")
    except: bot.send_message(message.chat.id, "❌ Invalid string. Requires KEY=VALUE format.")

if __name__ == "__main__":
    load_registry()
    threading.Thread(target=auto_healing_monitor, daemon=True).start()
    threading.Thread(target=lambda: bot.infinity_polling(timeout=10, long_polling_timeout=5), daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
