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
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

try:
    import psutil
except ImportError:
    psutil = None

# ==========================================
# ⚙️ CONFIGS & CREDENTIALS (MASTER)
# ==========================================
ADMIN_ID = 7193432903
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8483068207:AAEq3LPHIYlug4qtQnkc9dQB2u-r6kQm1cs")
GH_TOKEN = os.environ.get("GH_TOKEN", "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")
GH_REPO = os.environ.get("GH_REPO", "my-hosted-bots-backup")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# System Directories & Globals
HOST_DIR = "hosted_env"
LOG_DIR = os.path.join(HOST_DIR, "logs")
TEMP_DIR = os.path.join(HOST_DIR, "temp_uploads")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

hosted_processes = {}  
user_deploy_states = {} # Holds temporary state for Auto/Manual package selection
user_chats = set()
banned_users = set()
user_custom_envs = {}
engine_start_time = time.time()
MAINTENANCE_MODE = False  

PIP_MAP = {
    "telebot": "pyTelegramBotAPI", "PIL": "Pillow", "bs4": "beautifulsoup4",
    "cv2": "opencv-python", "fitz": "PyMuPDF", "yaml": "pyyaml",
    "crypto": "pycryptodome", "sklearn": "scikit-learn", "telegram": "python-telegram-bot",
    "discord": "discord.py", "pyrogram": "pyrogram tgcrypto", "aiogram": "aiogram",
    "dotenv": "python-dotenv", "dateutil": "python-dateutil", "jose": "python-jose",
    "jwt": "PyJWT", "dantic": "pydantic"
}
BUILTINS = sys.builtin_module_names

@app.route('/')
def home():
    active_count = len([p for p in hosted_processes.values() if p["process"] and p["process"].poll() is None])
    return f"⚡ Bulletproof Python Host Engine is Live 24/7! Active Bots: {active_count}"

def is_admin(user_id): return int(user_id) == ADMIN_ID
def is_banned(user_id): return user_id in banned_users

def get_readable_uptime(seconds):
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {mins}m {secs}s"

def get_progress_bar(percent):
    filled = int(percent / 10)
    return "█" * filled + "░" * (10 - filled)

def generate_bot_id():
    while True:
        b_id = f"BOT-{random.randint(1000, 9999)}"
        if b_id not in hosted_processes and b_id not in user_deploy_states:
            return b_id

# AST Scanner & Installer
def deep_analyze_imports(file_path):
    detected_modules = set()
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            tree = ast.parse(f.read(), filename=file_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names: detected_modules.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module: detected_modules.add(node.module.split('.')[0])
    except:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
        detected_modules.update(re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE))

    return [PIP_MAP.get(m, m) for m in detected_modules if m not in BUILTINS and not os.path.exists(os.path.join(HOST_DIR, f"{m}.py"))]

def auto_install_packages(modules, chat_id, progress_msg):
    if not modules: return True
    for index, mod in enumerate(modules, start=1):
        try:
            pct = int((index / len(modules)) * 100)
            bot.edit_message_text(f"🧠 **Smart Auto-Installing:**\n`[{get_progress_bar(pct)}] {pct}%` ➔ `{mod}`", chat_id, progress_msg.message_id, parse_mode="Markdown")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', *mod.split(), '--no-cache-dir'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except: pass
    return True

def backup_file_to_github(filename, content_bytes):
    if not GH_TOKEN or GH_TOKEN.startswith("YOUR_"): return False
    try:
        url = f"https://api.github.com/repos/{GH_TOKEN.split('_')[0]}/{GH_REPO}/contents/{filename}"
        headers = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        get_res = requests.get(url, headers=headers)
        data = {"message": f"Auto backup of {filename}", "content": base64.b64encode(content_bytes).decode("utf-8")}
        if get_res.status_code == 200: data["sha"] = get_res.json().get("sha")
        requests.put(url, headers=headers, json=data)
        return True
    except: return False

# Process Manager (Linked with Bot IDs)
def run_script_process(bot_id, filename, owner_id):
    script_path = os.path.join(HOST_DIR, filename)
    log_file_path = os.path.join(LOG_DIR, f"{bot_id}.log")
    log_out = open(log_file_path, "a", encoding="utf-8")
    
    custom_env = os.environ.copy()
    if owner_id in user_custom_envs: custom_env.update(user_custom_envs[owner_id])
    
    proc = subprocess.Popen([sys.executable, filename], cwd=HOST_DIR, stdout=log_out, stderr=log_out, env=custom_env, text=True)
    hosted_processes[bot_id] = {"process": proc, "filename": filename, "owner_id": owner_id, "start_time": time.time(), "log_file": log_file_path, "retries": 0}

def stop_script_process(bot_id):
    if bot_id in hosted_processes:
        proc = hosted_processes[bot_id]["process"]
        if proc.poll() is None:
            try: proc.terminate(); proc.wait(timeout=2)
            except: proc.kill()
        del hosted_processes[bot_id]

# Feature: Anti-Crash Watchdog & Self-Healing
def auto_healing_monitor():
    while True:
        time.sleep(10)
        for bot_id, data in list(hosted_processes.items()):
            proc = data["process"]
            owner_id = data["owner_id"]
            filename = data["filename"]
            
            if psutil and proc.poll() is None:
                try:
                    p = psutil.Process(proc.pid)
                    if p.cpu_percent(interval=1.0) > 85.0:  
                        stop_script_process(bot_id)
                        bot.send_message(owner_id, f"🚨 **AUTO-KILL:** Your bot `{bot_id}` was taking too much CPU/RAM and was force-stopped!")
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
                    try:
                        bot.send_message(owner_id, f"⚡ **Self-Healing:** Auto-installing `{target_pkg}` for `{bot_id}`...", parse_mode="Markdown")
                        subprocess.check_call([sys.executable, '-m', 'pip', 'install', target_pkg])
                    except: pass
                    run_script_process(bot_id, filename, owner_id)
                elif data["retries"] < 3:
                    data["retries"] += 1
                    run_script_process(bot_id, filename, owner_id)

# ==========================================
# 🎛️ THE 5-MENU PROFESSIONAL ECOSYSTEM
# ==========================================
def get_user_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    user_bots = [b for b, d in hosted_processes.items() if (d["owner_id"] == user_id or is_admin(user_id)) and d["process"].poll() is None]
    
    markup.add(
        InlineKeyboardButton("🚀 Deploy Python Bot", callback_data="host_file"),
        InlineKeyboardButton("🔍 Search Bot ID Hub", callback_data="search_hub"),
        InlineKeyboardButton(f"🤖 Managed Bots ({len(user_bots)})", callback_data="my_bots"),
        InlineKeyboardButton("🛑 Stop All My Bots", callback_data="stop_my_bots"),
        InlineKeyboardButton("🔑 Manage ENV Vars", callback_data="manage_env"),
        InlineKeyboardButton("📂 Browse / ZIP Backup", callback_data="browse_files"),
        InlineKeyboardButton("⏰ Server Uptime & Ping", callback_data="server_ping")
    )
    if is_admin(user_id): markup.add(InlineKeyboardButton("👑 Master Admin Controls", callback_data="admin_panel"))
    return markup

def get_search_hub_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔍 Find Bot by ID", callback_data="search_by_id"),
        InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu")
    )
    return markup

def get_package_menu(bot_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🧠 Auto Detect & Install", callback_data=f"pkg_auto:{bot_id}"),
        InlineKeyboardButton("📝 Manual Install (.txt)", callback_data=f"pkg_manual:{bot_id}")
    )
    return markup

def get_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    maint_status = "🟢 ON" if MAINTENANCE_MODE else "🔴 OFF"
    markup.add(
        InlineKeyboardButton(f"🛠 Maintenance: {maint_status}", callback_data="toggle_maintenance"),
        InlineKeyboardButton("🌐 All Managed Bots", callback_data="list_all_bots"),
        InlineKeyboardButton("🚨 EMERGENCY KILL ALL", callback_data="emergency_kill"),
        InlineKeyboardButton("🧹 Purge Cache", callback_data="server_clean"),
        InlineKeyboardButton("📢 Broadcast Msg", callback_data="broadcast_menu"),
        InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    if is_banned(user_id): return
    user_chats.add(message.chat.id)
    role = "👑 Master Admin" if is_admin(user_id) else "👤 Standard User"
    
    if MAINTENANCE_MODE and not is_admin(user_id):
        bot.send_message(message.chat.id, "🛠 **SERVER UNDER MAINTENANCE!**\nNew uploads are temporarily paused.")
        return
        
    bot.send_message(message.chat.id, f"⚡ **PYTHON CLOUD HOSTING ENGINE** ⚡\n\n🆔 **Your ID:** `{user_id}`\n🔰 **Role:** {role}\n\nUpload a `.py` file or `.zip` project:", parse_mode="Markdown", reply_markup=get_user_menu(user_id))

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    global MAINTENANCE_MODE
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    data = call.data
    user_chats.add(chat_id)

    if data == "main_menu":
        bot.send_message(chat_id, "🎛️ **Main Dashboard:**", reply_markup=get_user_menu(user_id))

    elif data == "admin_panel" and is_admin(user_id):
        bot.send_message(chat_id, "👑 **Admin Master Controls:**", reply_markup=get_admin_menu())

    elif data == "search_hub":
        bot.send_message(chat_id, "🔍 **Identity Search Hub:**", reply_markup=get_search_hub_menu())

    elif data == "host_file":
        if MAINTENANCE_MODE and not is_admin(user_id): return bot.answer_callback_query(call.id, "Server Maintenance Active", show_alert=True)
        bot.send_message(chat_id, "📂 **Upload your Python `.py` or `.zip` project:**")
        bot.register_next_step_handler(call.message, process_script_upload)
        
    elif data == "search_by_id":
        bot.send_message(chat_id, "🔍 Enter Bot ID (e.g., `BOT-1234`):", parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_search_bot)

    elif data.startswith("pkg_auto:"):
        bot_id = data.split(":")[1]
        msg = bot.edit_message_text("🧠 Auto-Install Engine Started...", chat_id, call.message.message_id)
        threading.Thread(target=finalize_deployment, args=(chat_id, msg.message_id, bot_id, "auto")).start()

    elif data.startswith("pkg_manual:"):
        bot_id = data.split(":")[1]
        bot.edit_message_text("📝 **Manual Installation:**\n\nSend your `requirements.txt` file now:", chat_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, lambda m: handle_manual_reqs(m, bot_id))

    elif data == "toggle_maintenance" and is_admin(user_id):
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_admin_menu())
        bot.answer_callback_query(call.id, f"Maintenance: {'ON' if MAINTENANCE_MODE else 'OFF'}", show_alert=True)

    elif data == "server_ping":
        latency = round((time.time() - engine_start_time) * 1000, 2)
        ram = psutil.virtual_memory().percent if psutil else "N/A"
        bot.send_message(chat_id, f"📡 **Latency:** `{latency}ms`\n⏱️ **Uptime:** `{get_readable_uptime(time.time() - engine_start_time)}`\n💾 **RAM Use:** `{ram}%`", parse_mode="Markdown")

    elif data == "manage_env":
        bot.send_message(chat_id, "🔑 **Send ENV Var format:** `KEY=VALUE`")
        bot.register_next_step_handler(call.message, save_env_var)

    elif data == "server_clean" and is_admin(user_id):
        shutil.rmtree(os.path.join(HOST_DIR, "__pycache__"), ignore_errors=True)
        bot.send_message(chat_id, "🧹 **Server cache purged!**")

    elif data == "browse_files":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("📦 EXPORT PROJECT BACKUP (ZIP)", callback_data="export_zip"))
        markup.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.send_message(chat_id, "📂 **Files Explorer:**", reply_markup=markup)

    elif data == "export_zip":
        bot.send_message(chat_id, "📦 Compressing files...")
        zip_path = f"backup_{user_id}.zip"
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for root, _, files in os.walk(HOST_DIR):
                for f in files:
                    if is_admin(user_id) or not f.endswith('.log'): 
                        zipf.write(os.path.join(root, f), arcname=f)
        bot.send_document(chat_id, open(zip_path, 'rb'))
        os.remove(zip_path)

    elif data in ["my_bots", "list_all_bots"]:
        if data == "list_all_bots" and not is_admin(user_id): return
        items = [(bid, d) for bid, d in hosted_processes.items() if is_admin(user_id) or d["owner_id"] == user_id]
        if not items: return bot.send_message(chat_id, "📂 No hosted bots found.", reply_markup=get_user_menu(user_id))
        
        markup = InlineKeyboardMarkup(row_width=1)
        for bid, d in items:
            status = "🟢" if d["process"].poll() is None else "🔴"
            markup.add(InlineKeyboardButton(f"{status} {bid} ({d['filename']})", callback_data=f"manage:{bid}"))
        markup.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.send_message(chat_id, "🤖 **Managed Bots:**", reply_markup=markup)

    elif data.startswith("manage:"):
        bot_id = data.split(":", 1)[1]
        if bot_id not in hosted_processes: return bot.answer_callback_query(call.id, "Bot not found.", show_alert=True)
        proj = hosted_processes[bot_id]
        is_running = proj["process"].poll() is None
        markup = InlineKeyboardMarkup(row_width=2)
        
        if is_running: markup.add(InlineKeyboardButton("🛑 Stop", callback_data=f"stop:{bot_id}"), InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{bot_id}"))
        else: markup.add(InlineKeyboardButton("▶️ Start", callback_data=f"start:{bot_id}"))
        
        markup.add(
            InlineKeyboardButton("📜 Live Logs", callback_data=f"log:{bot_id}"),
            InlineKeyboardButton("📝 Instant Edit", callback_data=f"edit_code:{bot_id}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"del:{bot_id}"),
            InlineKeyboardButton("🔙 Back", callback_data="main_menu")
        )
        bot.send_message(chat_id, f"⚙️ **Control Panel:** `{bot_id}`", parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("edit_code:"):
        bot_id = data.split(":", 1)[1]
        proj = hosted_processes[bot_id]
        filepath = os.path.join(HOST_DIR, proj["filename"])
        with open(filepath, 'r', encoding='utf-8') as f: code = f.read()
        if len(code) > 3500:
            bot.send_message(chat_id, "⚠️ File is too large to edit in Telegram.")
        else:
            bot.send_message(chat_id, f"📝 **Instant Edit (`{bot_id}` - {proj['filename']}):**\n\nSend your updated code below:")
            bot.register_next_step_handler(call.message, lambda m: save_edited_code(m, bot_id))

    elif data.startswith("log:"):
        bot_id = data.split(":", 1)[1]
        log_path = hosted_processes[bot_id]["log_file"]
        content = "No logs yet."
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as logf: content = logf.read()[-2500:] or content
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Refresh", callback_data=f"log:{bot_id}"))
        try: bot.edit_message_text(f"📜 **Live Logs (`{bot_id}`):**\n```text\n{content}\n```", chat_id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
        except: bot.send_message(chat_id, f"📜 **Live Logs (`{bot_id}`):**\n```text\n{content}\n```", parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("stop:"):
        bid = data.split(":", 1)[1]
        stop_script_process(bid)
        bot.send_message(chat_id, f"🛑 Bot `{bid}` stopped.")
    elif data.startswith("start:"): 
        bid = data.split(":", 1)[1]
        p = hosted_processes[bid]
        run_script_process(bid, p["filename"], p["owner_id"])
        bot.send_message(chat_id, f"✅ Bot `{bid}` started!")
    elif data.startswith("restart:"): 
        bid = data.split(":", 1)[1]
        p = hosted_processes[bid]
        stop_script_process(bid)
        run_script_process(bid, p["filename"], p["owner_id"])
        bot.send_message(chat_id, f"🔄 Bot `{bid}` restarted!")
    elif data.startswith("del:"): 
        bid = data.split(":", 1)[1]
        p = hosted_processes.get(bid)
        if p:
            stop_script_process(bid)
            try: os.remove(os.path.join(HOST_DIR, p["filename"]))
            except: pass
        bot.send_message(chat_id, f"🗑️ Bot `{bid}` deleted.")

    elif data == "emergency_kill" and is_admin(user_id):
        for bid in list(hosted_processes.keys()): stop_script_process(bid)
        bot.send_message(chat_id, "🚨 **ALL BOTS STOPPED!**", parse_mode="Markdown")

    elif data == "stop_my_bots":
        for bid, d in list(hosted_processes.items()):
            if d["owner_id"] == user_id: stop_script_process(bid)
        bot.send_message(chat_id, "🛑 Your active bots stopped.")

    elif data == "broadcast_menu" and is_admin(user_id):
        bot.send_message(chat_id, "📢 **Send announcement / Ad message (Text, Photo, etc.):**")
        bot.register_next_step_handler(call.message, process_broadcast)

# Deployment Workflow Functions
def process_script_upload(message):
    user_id = message.from_user.id
    if not message.document: return
    filename = message.document.file_name
    
    if not (filename.endswith('.py') or filename.endswith('.zip')): return bot.send_message(message.chat.id, "❌ Valid `.py` ya `.zip` file bhejein.")
    
    bot_id = generate_bot_id()
    progress = bot.send_message(message.chat.id, f"🔄 **Assigned ID:** `{bot_id}`\nDownloading File...", parse_mode="Markdown")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        target_script = f"{bot_id}_{filename}"
        
        if filename.endswith('.zip'):
            zip_path = os.path.join(HOST_DIR, target_script)
            with open(zip_path, "wb") as f: f.write(downloaded)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(HOST_DIR)
            os.remove(zip_path)
            
            possible_mains = ['main.py', 'bot.py', 'app.py']
            found = False
            for p in possible_mains:
                if os.path.exists(os.path.join(HOST_DIR, p)):
                    new_name = f"{bot_id}_{p}"
                    os.rename(os.path.join(HOST_DIR, p), os.path.join(HOST_DIR, new_name))
                    target_script = new_name
                    found = True
                    break
            if not found: return bot.edit_message_text("❌ `.zip` mein `main.py` ya `bot.py` nahi mila!", message.chat.id, progress.message_id)
        else:
            with open(os.path.join(HOST_DIR, target_script), "wb") as f: f.write(downloaded)
        
        user_deploy_states[bot_id] = {"owner_id": user_id, "filename": target_script, "msg_id": progress.message_id}
        bot.edit_message_text(f"📦 **Identity Created:** `{bot_id}`\n\nPackages kaise install karne hain?", message.chat.id, progress.message_id, parse_mode="Markdown", reply_markup=get_package_menu(bot_id))
    except Exception as e:
        bot.edit_message_text(f"❌ **Error:** `{str(e)}`", message.chat.id, progress.message_id, parse_mode="Markdown")

def finalize_deployment(chat_id, msg_id, bot_id, install_type, manual_req_path=None):
    state = user_deploy_states.get(bot_id)
    if not state: return
    user_id, target_script = state["owner_id"], state["filename"]
    script_path = os.path.join(HOST_DIR, target_script)
    
    if install_type == "manual" and manual_req_path and os.path.exists(manual_req_path):
        bot.edit_message_text(f"📦 Installing requirements for `{bot_id}`...", chat_id, msg_id)
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', manual_req_path, '--no-cache-dir'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        needed_packages = deep_analyze_imports(script_path)
        auto_install_packages(needed_packages, chat_id, type('obj', (object,), {'message_id': msg_id})())

    bot.edit_message_text(f"⚙️ Compiling Code for `{bot_id}`...", chat_id, msg_id)
    try: py_compile.compile(script_path, doraise=True)
    except py_compile.PyCompileError as sys_err: return bot.edit_message_text(f"⚠️ Syntax Error:\n```text\n{sys_err}\n```", chat_id, msg_id, parse_mode="Markdown")

    backup_file_to_github(target_script, open(script_path, 'rb').read())
    run_script_process(bot_id, target_script, user_id)

    bot.edit_message_text(f"🚀 **Deployment Complete!**\n\n📌 **Identity:** `{bot_id}`\n🚀 Status: LIVE", chat_id, msg_id, parse_mode="Markdown")
    bot.send_message(chat_id, "🎛️ **Manage Options:**", reply_markup=get_control_panel(bot_id, True))

def handle_manual_reqs(message, bot_id):
    if not message.document: return bot.send_message(message.chat.id, "❌ Please send a valid requirements.txt file.")
    try:
        req_p = os.path.join(HOST_DIR, f"req_{bot_id}.txt")
        file_info = bot.get_file(message.document.file_id)
        with open(req_p, "wb") as f: f.write(bot.download_file(file_info.file_path))
        msg = bot.send_message(message.chat.id, "📥 Installing custom requirements...")
        threading.Thread(target=finalize_deployment, args=(message.chat.id, msg.message_id, bot_id, "manual", req_p)).start()
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

def process_search_bot(message):
    query = message.text.strip().upper()
    if not query.startswith("BOT-"): query = f"BOT-{query}"
    if query in hosted_processes:
        proj = hosted_processes[query]
        is_run = proj["process"].poll() is None
        bot.send_message(message.chat.id, f"🔍 **Bot Found:** `{query}`", parse_mode="Markdown", reply_markup=get_control_panel(query, is_run))
    else:
        bot.send_message(message.chat.id, f"❌ Identity `{query}` not found.")

def save_edited_code(message, bot_id):
    if not message.text: return bot.send_message(message.chat.id, "Edit cancelled.")
    proj = hosted_processes.get(bot_id)
    if not proj: return bot.send_message(message.chat.id, "Bot not found.")
    
    script_path = os.path.join(HOST_DIR, proj["filename"])
    stop_script_process(bot_id)
    with open(script_path, 'w', encoding='utf-8') as f: f.write(message.text)
    run_script_process(bot_id, proj["filename"], proj["owner_id"])
    bot.send_message(message.chat.id, f"✅ `{bot_id}` updated & restarted successfully!", reply_markup=get_control_panel(bot_id, True))

def save_env_var(message):
    try:
        key, val = message.text.split("=", 1)
        uid = message.from_user.id
        user_custom_envs.setdefault(uid, {})[key.strip()] = val.strip()
        bot.send_message(message.chat.id, f"✅ **ENV Variable Saved:** `{key.strip()}`", parse_mode="Markdown")
    except: bot.send_message(message.chat.id, "❌ Invalid format. Use KEY=VALUE")

def process_broadcast(message):
    if not is_admin(message.from_user.id): return
    count = 0
    for target_id in list(user_chats):
        try:
            bot.copy_message(chat_id=target_id, from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
        except: pass
    bot.send_message(message.chat.id, f"✅ Broadcast sent to `{count}` chats!", parse_mode="Markdown", reply_markup=get_admin_menu())

if __name__ == "__main__":
    threading.Thread(target=auto_healing_monitor, daemon=True).start()
    threading.Thread(target=lambda: bot.infinity_polling(timeout=10, long_polling_timeout=5), daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
