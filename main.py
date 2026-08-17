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
os.makedirs(LOG_DIR, exist_ok=True)

hosted_processes = {}  
user_chats = set()
banned_users = set()
user_custom_envs = {}
engine_start_time = time.time()
MAINTENANCE_MODE = False  # Feature: Maintenance Mode

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
    return f"⚡ Ultra-Pro Host Engine is Live 24/7! Active Bots: {len(hosted_processes)}"

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

# Process Manager
def run_script_process(filename, owner_id):
    script_path = os.path.join(HOST_DIR, filename)
    log_file_path = os.path.join(LOG_DIR, f"{filename}.log")
    log_out = open(log_file_path, "a", encoding="utf-8")
    
    custom_env = os.environ.copy()
    if owner_id in user_custom_envs: custom_env.update(user_custom_envs[owner_id])
    
    proc = subprocess.Popen([sys.executable, filename], cwd=HOST_DIR, stdout=log_out, stderr=log_out, env=custom_env, text=True)
    hosted_processes[filename] = {"process": proc, "owner_id": owner_id, "start_time": time.time(), "log_file": log_file_path, "retries": hosted_processes.get(filename, {}).get("retries", 0)}

def stop_script_process(filename):
    if filename in hosted_processes:
        proc = hosted_processes[filename]["process"]
        if proc.poll() is None:
            try: proc.terminate(); proc.wait(timeout=2)
            except: proc.kill()
        del hosted_processes[filename]

# Feature: Anti-Crash Watchdog & Self-Healing
def auto_healing_monitor():
    while True:
        time.sleep(10)
        for filename, data in list(hosted_processes.items()):
            proc = data["process"]
            owner_id = data["owner_id"]
            
            # Anti-Crash CPU/RAM Watchdog (Admin Feature)
            if psutil and proc.poll() is None:
                try:
                    p = psutil.Process(proc.pid)
                    if p.cpu_percent(interval=1.0) > 85.0:  # If script eats > 85% CPU continuously
                        stop_script_process(filename)
                        bot.send_message(owner_id, f"🚨 **AUTO-KILL:** Your script `{filename}` was taking too much CPU/RAM and was force-stopped to protect the server!")
                        if not is_admin(owner_id): bot.send_message(ADMIN_ID, f"🚨 Watchdog killed `{filename}` (Owner: {owner_id}) for CPU abuse.")
                        continue
                except: pass

            # Self-Healing Crash Recovery
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
                        bot.send_message(owner_id, f"⚡ **Self-Healing:** Auto-installing missing `{target_pkg}` for `{filename}`...", parse_mode="Markdown")
                        subprocess.check_call([sys.executable, '-m', 'pip', 'install', target_pkg])
                    except: pass
                    run_script_process(filename, owner_id)
                elif data["retries"] < 3:
                    data["retries"] += 1
                    run_script_process(filename, owner_id)

# UI Menus
def get_user_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    user_bots = [f for f, d in hosted_processes.items() if (d["owner_id"] == user_id or is_admin(user_id)) and d["process"].poll() is None]
    
    markup.add(
        InlineKeyboardButton("🚀 Host .py / .zip", callback_data="host_file"),
        InlineKeyboardButton("🐙 Deploy GitHub Repo", callback_data="host_github"),
        InlineKeyboardButton(f"🤖 Managed Bots ({len(user_bots)})", callback_data="my_bots"),
        InlineKeyboardButton("🛑 Stop All My Bots", callback_data="stop_my_bots"),
        InlineKeyboardButton("📦 Upload reqs.txt", callback_data="host_req"),
        InlineKeyboardButton("🔑 Manage ENV Vars", callback_data="manage_env"),
        InlineKeyboardButton("📂 Browse / ZIP Backup", callback_data="browse_files"),
        InlineKeyboardButton("⏰ Server Uptime & Ping", callback_data="server_ping")
    )
    if is_admin(user_id): markup.add(InlineKeyboardButton("👑 Master Admin Controls", callback_data="admin_panel"))
    return markup

def get_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    maint_status = "🟢 ON" if MAINTENANCE_MODE else "🔴 OFF"
    markup.add(
        InlineKeyboardButton("💻 Root Terminal", callback_data="admin_terminal"),
        InlineKeyboardButton("💉 Mass Code Inject", callback_data="admin_inject"),
        InlineKeyboardButton(f"🛠 Maintenance: {maint_status}", callback_data="toggle_maintenance"),
        InlineKeyboardButton("🌐 All Bots Control", callback_data="list_all_bots"),
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
        bot.send_message(message.chat.id, "🛠 **SERVER UNDER MAINTENANCE!**\nNew uploads are temporarily paused. Existing bots are still running.")
        return
        
    bot.send_message(message.chat.id, f"⚡ **ULTRA-PRO HOSTING ENGINE** ⚡\n\n🆔 **Your ID:** `{user_id}`\n🔰 **Role:** {role}\n\nUpload a `.py` file, `.zip` project, or clone a Repo!", parse_mode="Markdown", reply_markup=get_user_menu(user_id))

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

    elif data == "host_file":
        if MAINTENANCE_MODE and not is_admin(user_id): return bot.answer_callback_query(call.id, "Server Maintenance Active", show_alert=True)
        bot.send_message(chat_id, "📂 **Upload your `.py` or `.zip` project:**")
        bot.register_next_step_handler(call.message, process_script_upload)
        
    elif data == "host_github":
        if MAINTENANCE_MODE and not is_admin(user_id): return bot.answer_callback_query(call.id, "Server Maintenance Active", show_alert=True)
        bot.send_message(chat_id, "🐙 **Send Public GitHub Repo URL:**\n*(e.g., https://github.com/user/repo)*")
        bot.register_next_step_handler(call.message, process_github_clone)

    elif data == "admin_terminal" and is_admin(user_id):
        bot.send_message(chat_id, "💻 **ROOT TERMINAL ACTIVE.**\nSend any Bash/Linux command (e.g. `ls -la`, `pip freeze`). Type 'exit' to cancel.")
        bot.register_next_step_handler(call.message, process_terminal_cmd)
        
    elif data == "admin_inject" and is_admin(user_id):
        bot.send_message(chat_id, "💉 **Send Python code to INJECT into ALL `.py` files:**\n(It will be added to the very top of all scripts)")
        bot.register_next_step_handler(call.message, process_mass_inject)

    elif data == "toggle_maintenance" and is_admin(user_id):
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_admin_menu())
        bot.answer_callback_query(call.id, f"Maintenance: {'ON' if MAINTENANCE_MODE else 'OFF'}", show_alert=True)

    elif data == "host_req":
        bot.send_message(chat_id, "📜 **Upload `requirements.txt`:**")
        bot.register_next_step_handler(call.message, process_req_upload)

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
                    # Admin gets everything, User gets only files they own (or basic files)
                    if is_admin(user_id) or not f.endswith('.log'): 
                        zipf.write(os.path.join(root, f), arcname=f)
        bot.send_document(chat_id, open(zip_path, 'rb'))
        os.remove(zip_path)

    elif data in ["my_bots", "list_all_bots"]:
        if data == "list_all_bots" and not is_admin(user_id): return
        files = [f for f in os.listdir(HOST_DIR) if f.endswith('.py')]
        if not is_admin(user_id): files = [f for f in files if hosted_processes.get(f, {}).get("owner_id") == user_id]
        if not files: return bot.send_message(chat_id, "📂 No hosted bots found.", reply_markup=get_user_menu(user_id))
        
        markup = InlineKeyboardMarkup(row_width=1)
        for f in files:
            status = "🟢" if f in hosted_processes and hosted_processes[f]["process"].poll() is None else "🔴"
            markup.add(InlineKeyboardButton(f"{status} {f}", callback_data=f"manage:{f}"))
        markup.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.send_message(chat_id, "🤖 **Managed Bots:**", reply_markup=markup)

    elif data.startswith("manage:"):
        filename = data.split(":", 1)[1]
        is_running = filename in hosted_processes and hosted_processes[filename]["process"].poll() is None
        markup = InlineKeyboardMarkup(row_width=2)
        
        if is_running: markup.add(InlineKeyboardButton("🛑 Stop", callback_data=f"stop:{filename}"), InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{filename}"))
        else: markup.add(InlineKeyboardButton("▶️ Start", callback_data=f"start:{filename}"))
        
        markup.add(
            InlineKeyboardButton("📜 Live Logs", callback_data=f"log:{filename}"),
            InlineKeyboardButton("📝 Edit Code", callback_data=f"edit_code:{filename}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"del:{filename}"),
            InlineKeyboardButton("🔙 Back", callback_data="main_menu")
        )
        bot.send_message(chat_id, f"⚙️ **Control Panel:** `{filename}`", parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("edit_code:"):
        filename = data.split(":", 1)[1]
        filepath = os.path.join(HOST_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f: code = f.read()
        if len(code) > 3500:
            bot.send_message(chat_id, "⚠️ File is too large to edit in Telegram. Please download, edit, and re-upload.")
        else:
            bot.send_message(chat_id, f"📝 **In-Chat Editor (`{filename}`):**\n\nCopy the code below, edit it, and send it back to me. Type 'cancel' to abort.")
            bot.send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
            bot.register_next_step_handler(call.message, lambda m: save_edited_code(m, filename))

    elif data.startswith("log:"):
        filename = data.split(":", 1)[1]
        log_path = os.path.join(LOG_DIR, f"{filename}.log")
        content = "No logs yet."
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as logf: content = logf.read()[-2500:] or content
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Refresh Logs", callback_data=f"log:{filename}"))
        try: bot.edit_message_text(f"📜 **Live Logs (`{filename}`):**\n```text\n{content}\n```", chat_id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
        except: bot.send_message(chat_id, f"📜 **Live Logs (`{filename}`):**\n```text\n{content}\n```", parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("stop:"): stop_script_process(data.split(":", 1)[1]); bot.send_message(chat_id, f"🛑 Script stopped.")
    elif data.startswith("start:"): run_script_process(data.split(":", 1)[1], user_id); bot.send_message(chat_id, f"✅ Script started!")
    elif data.startswith("restart:"): fn = data.split(":", 1)[1]; stop_script_process(fn); run_script_process(fn, user_id); bot.send_message(chat_id, f"🔄 Script restarted!")
    elif data.startswith("del:"): 
        fn = data.split(":", 1)[1]
        stop_script_process(fn)
        try: os.remove(os.path.join(HOST_DIR, fn))
        except: pass
        bot.send_message(chat_id, f"🗑️ `{fn}` deleted.")

    elif data == "emergency_kill" and is_admin(user_id):
        for fn in list(hosted_processes.keys()): stop_script_process(fn)
        bot.send_message(chat_id, "🚨 **ALL BOTS STOPPED!**", parse_mode="Markdown")

    elif data == "stop_my_bots":
        for fn, d in list(hosted_processes.items()):
            if d["owner_id"] == user_id: stop_script_process(fn)
        bot.send_message(chat_id, "🛑 Your active bots stopped.")

    elif data == "broadcast_menu" and is_admin(user_id):
        bot.send_message(chat_id, "📢 **Enter message to broadcast:**")
        bot.register_next_step_handler(call.message, process_broadcast)

# New Feature Functions
def save_edited_code(message, filename):
    if message.text.lower() == 'cancel': return bot.send_message(message.chat.id, "Edit cancelled.")
    filepath = os.path.join(HOST_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f: f.write(message.text)
    bot.send_message(message.chat.id, f"✅ `{filename}` updated! Restarting bot...")
    stop_script_process(filename)
    run_script_process(filename, message.from_user.id)

def process_terminal_cmd(message):
    if message.text.lower() == 'exit': return bot.send_message(message.chat.id, "Terminal closed.")
    try: 
        res = subprocess.getoutput(message.text)
        bot.send_message(message.chat.id, f"💻 **Output:**\n```bash\n{res[:4000]}\n```", parse_mode="Markdown")
    except Exception as e: bot.send_message(message.chat.id, str(e))
    bot.register_next_step_handler(message, process_terminal_cmd)

def process_mass_inject(message):
    code = message.text
    count = 0
    for f in os.listdir(HOST_DIR):
        if f.endswith('.py'):
            p = os.path.join(HOST_DIR, f)
            with open(p, 'r') as file: old = file.read()
            with open(p, 'w') as file: file.write(f"{code}\n\n{old}")
            count += 1
    bot.send_message(message.chat.id, f"💉 **Injected successfully into {count} scripts!**")

def process_github_clone(message):
    url = message.text.strip()
    if not url.startswith("http"): return bot.send_message(message.chat.id, "Invalid URL.")
    msg = bot.send_message(message.chat.id, "🐙 Cloning repository...")
    repo_name = url.split('/')[-1].replace('.git', '')
    dest = os.path.join(HOST_DIR, repo_name)
    try:
        subprocess.check_output(['git', 'clone', url, dest])
        # Auto-detect main.py or bot.py
        main_script = None
        for f in os.listdir(dest):
            if f in ['main.py', 'bot.py', 'app.py']: main_script = f; break
        
        if main_script:
            shutil.copy(os.path.join(dest, main_script), os.path.join(HOST_DIR, main_script))
            bot.edit_message_text(f"✅ Cloned! Hosting `{main_script}`...", message.chat.id, msg.message_id)
            run_script_process(main_script, message.from_user.id)
        else:
            bot.edit_message_text("✅ Cloned! Folder saved, but couldn't auto-detect main.py.", message.chat.id, msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Error cloning: {str(e)}", message.chat.id, msg.message_id)

def save_env_var(message):
    try:
        key, val = message.text.split("=", 1)
        uid = message.from_user.id
        if uid not in user_custom_envs: user_custom_envs[uid] = {}
        user_custom_envs[uid][key.strip()] = val.strip()
        bot.send_message(message.chat.id, f"✅ **ENV Variable Saved:** `{key.strip()}`", parse_mode="Markdown")
    except: bot.send_message(message.chat.id, "❌ Invalid format.")

def process_script_upload(message):
    user_id = message.from_user.id
    if not message.document: return
    filename = message.document.file_name
    
    if not (filename.endswith('.py') or filename.endswith('.zip')): return bot.send_message(message.chat.id, "❌ Valid `.py` ya `.zip` file bhejein.")
    progress = bot.send_message(message.chat.id, f"🔄 **Step 1: Downloading File...**\n`[{get_progress_bar(20)}] 20%`", parse_mode="Markdown")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        target_script = filename
        
        if filename.endswith('.zip'):
            zip_path = os.path.join(HOST_DIR, filename)
            with open(zip_path, "wb") as f: f.write(downloaded)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(HOST_DIR)
            os.remove(zip_path)
            
            # Smart Auto-Detect for ZIPs
            possible_mains = ['main.py', 'bot.py', 'app.py']
            found = False
            for p in possible_mains:
                if os.path.exists(os.path.join(HOST_DIR, p)): target_script = p; found = True; break
            if not found: return bot.edit_message_text("❌ `.zip` mein `main.py` ya `bot.py` nahi mila!", message.chat.id, progress.message_id)
        else:
            with open(os.path.join(HOST_DIR, filename), "wb") as f: f.write(downloaded)
        
        script_path = os.path.join(HOST_DIR, target_script)
        with open(script_path, 'r', encoding='utf-8', errors='ignore') as f: lines = len(f.readlines())
            
        needed_packages = deep_analyze_imports(script_path)
        auto_install_packages(needed_packages, message.chat.id, progress)

        bot.edit_message_text(f"⚙️ **Step 3: Compiling Code...**\n`[{get_progress_bar(80)}] 80%`", message.chat.id, progress.message_id, parse_mode="Markdown")
        try: py_compile.compile(script_path, doraise=True)
        except py_compile.PyCompileError as sys_err: bot.edit_message_text(f"⚠️ Syntax Error:\n```text\n{sys_err}\n```", message.chat.id, progress.message_id, parse_mode="Markdown")

        backup_file_to_github(target_script, open(script_path, 'rb').read())
        stop_script_process(target_script)
        run_script_process(target_script, user_id)

        bot.edit_message_text(f"✅ **Execution Complete!**\n`[{get_progress_bar(100)}] 100%`\n\n📝 **Lines:** `{lines}`\n🚀 `{target_script}` LIVE!", message.chat.id, progress.message_id, parse_mode="Markdown")
        bot.send_message(message.chat.id, "🎛️ **Manage Options:**", reply_markup=get_user_menu(user_id))
    except Exception as e: bot.edit_message_text(f"❌ **Error:** `{str(e)}`", message.chat.id, progress.message_id, parse_mode="Markdown")

def process_req_upload(message):
    if not message.document or not message.document.file_name.endswith('.txt'): return bot.send_message(message.chat.id, "❌ Send `requirements.txt`")
    msg = bot.send_message(message.chat.id, "📥 Installing reqs...")
    try:
        req_p = os.path.join(HOST_DIR, f"req_{message.from_user.id}.txt")
        with open(req_p, "wb") as f: f.write(bot.download_file(bot.get_file(message.document.file_id).file_path))
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_p])
        bot.edit_message_text("✅ Requirements installed!", message.chat.id, msg.message_id)
    except: bot.edit_message_text("❌ Error installing.", message.chat.id, msg.message_id)

def process_broadcast(message):
    if not is_admin(message.from_user.id): return
    count = 0
    msg_to_send = message.text or message.caption
    for target_id in list(user_chats):
        try:
            if message.content_type == 'text': bot.send_message(target_id, f"📢 **ANNOUNCEMENT:**\n\n{message.text}", parse_mode="Markdown")
            elif message.content_type == 'photo': bot.send_photo(target_id, message.photo[-1].file_id, caption=f"📢 **ANNOUNCEMENT:**\n\n{msg_to_send or ''}", parse_mode="Markdown")
            count += 1
        except: pass
    bot.send_message(message.chat.id, f"✅ Broadcast sent to `{count}` chats!", reply_markup=get_admin_menu())

def run_bot_polling(): bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    threading.Thread(target=auto_healing_monitor, daemon=True).start()
    threading.Thread(target=run_bot_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
