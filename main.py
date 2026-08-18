import os, re, ast, time, sys, subprocess, threading, base64, py_compile, requests, zipfile, shutil, socket, random
from flask import Flask, send_from_directory, abort
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

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=20)
app = Flask(__name__)

# ==========================================
# 📂 ABSOLUTE PATH SYSTEM DIRECTORIES
# ==========================================
BASE_DIR = os.path.abspath(os.getcwd())
HOST_DIR = os.path.join(BASE_DIR, "hosted_env")
LOG_DIR = os.path.join(HOST_DIR, "logs")
TEMP_DIR = os.path.join(HOST_DIR, "temp_uploads")
WEB_DIR = os.path.join(HOST_DIR, "web_public")

for d in [HOST_DIR, LOG_DIR, TEMP_DIR, WEB_DIR]:
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
    "cv2": "opencv-python", "fitz": "PyMuPDF", "yaml": "pyyaml",
    "crypto": "pycryptodome", "sklearn": "scikit-learn", "telegram": "python-telegram-bot",
    "discord": "discord.py", "pyrogram": "pyrogram tgcrypto", "aiogram": "aiogram",
    "dotenv": "python-dotenv", "dateutil": "python-dateutil", "jose": "python-jose",
    "jwt": "PyJWT", "dantic": "pydantic"
}
BUILTINS = sys.builtin_module_names

# ==========================================
# 🌐 INTEGRATED WEB SERVER (Flask)
# ==========================================
@app.route('/')
def home():
    return f"⚡ Ultra-Pro Host Engine is Live 24/7! Active Bots: {len(hosted_processes)}"

@app.route('/web/<bot_id>/<path:filename>')
def serve_user_web(bot_id, filename):
    if bot_id not in hosted_processes or hosted_processes[bot_id]["type"] != "web": abort(403)
    return send_from_directory(WEB_DIR, filename)

# ==========================================
# 🧠 SMART CORE UTILITIES
# ==========================================
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

def animate_progress(chat_id, msg_id, text, percent):
    bar_str = get_progress_bar(percent)
    try:
        bot.edit_message_text(f"⚙️ **System Engine Processing:**\n\n`[{bar_str}] {percent}%`\n> {text}", chat_id, msg_id, parse_mode="Markdown")
        time.sleep(0.6) 
    except: pass

def generate_bot_id():
    while True:
        b_id = f"BOT-{random.randint(1000, 9999)}"
        if b_id not in hosted_processes and b_id not in user_deploy_states:
            return b_id

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
    return [PIP_MAP.get(m, m) for m in detected_modules if m not in BUILTINS]

# ==========================================
# ⚙️ PROJECT PROCESS MANAGER (Stable & Absolute)
# ==========================================
def run_script_process(bot_id, filepath, owner_id, p_type="bot"):
    abs_path = os.path.abspath(filepath)
    if p_type == "web":
        hosted_processes[bot_id] = {"process": None, "owner_id": owner_id, "path": abs_path, "type": "web", "start_time": time.time()}
        return

    log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{bot_id}.log"))
    log_out = open(log_file_path, "a", encoding="utf-8")
    
    custom_env = os.environ.copy()
    if owner_id in user_custom_envs: custom_env.update(user_custom_envs[owner_id])
    
    proc = subprocess.Popen([sys.executable, abs_path], cwd=os.path.dirname(abs_path), stdout=log_out, stderr=log_out, env=custom_env, text=True)
    hosted_processes[bot_id] = {"process": proc, "owner_id": owner_id, "path": abs_path, "type": "bot", "start_time": time.time(), "log_file": log_file_path, "retries": hosted_processes.get(bot_id, {}).get("retries", 0)}

def stop_script_process(bot_id):
    if bot_id in hosted_processes:
        proc = hosted_processes[bot_id].get("process")
        if proc and proc.poll() is None:
            try: proc.terminate(); proc.wait(timeout=2)
            except: proc.kill()
        del hosted_processes[bot_id]

def auto_healing_monitor():
    while True:
        time.sleep(10)
        for bot_id, data in list(hosted_processes.items()):
            if data["type"] != "bot": continue
            proc = data["process"]
            owner_id = data["owner_id"]
            path = data["path"]
            
            if psutil and proc and proc.poll() is None:
                try:
                    p = psutil.Process(proc.pid)
                    if p.cpu_percent(interval=1.0) > 90.0 or p.memory_info().rss > 1024 * 1024 * 1024:
                        stop_script_process(bot_id)
                        bot.send_message(owner_id, f"🚨 **AUTO-KILL:** `{bot_id}` exceeded CPU/RAM limits!")
                        continue
                except: pass

            if proc and proc.poll() is not None: 
                log_path = data.get("log_file", "")
                missing_pkg = None
                if os.path.exists(log_path):
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as lf:
                        match = re.search(r"No module named '([^']+)'", lf.read()[-2000:])
                        if match: missing_pkg = match.group(1)

                if missing_pkg and data["retries"] < 5:
                    data["retries"] += 1
                    bot.send_message(owner_id, f"⚡ **Self-Healing:** Installing `{missing_pkg}` for `{bot_id}`...")
                    try: subprocess.check_call([sys.executable, '-m', 'pip', 'install', PIP_MAP.get(missing_pkg, missing_pkg)])
                    except: pass
                    run_script_process(bot_id, path, owner_id, "bot")
                elif data["retries"] < 3:
                    data["retries"] += 1
                    run_script_process(bot_id, path, owner_id, "bot")

# ==========================================
# 🎛️ UI MENUS
# ==========================================
def get_user_menu(user_id):
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton("🚀 Host .py / .zip / Web", callback_data="host_file"), InlineKeyboardButton("🔍 Search Bot ID", callback_data="search_hub"))
    m.add(InlineKeyboardButton("🤖 Managed Bots", callback_data="my_bots"), InlineKeyboardButton("🛑 Stop All My Bots", callback_data="stop_my_bots"))
    m.add(InlineKeyboardButton("📦 Upload reqs.txt", callback_data="host_req"), InlineKeyboardButton("🔑 Manage ENV Vars", callback_data="manage_env"))
    m.add(InlineKeyboardButton("📂 Browse / Backup", callback_data="browse_files"), InlineKeyboardButton("⏰ Server Health", callback_data="server_ping"))
    if is_admin(user_id): m.add(InlineKeyboardButton("👑 Master Admin Controls", callback_data="admin_panel"))
    return m

def get_search_hub_menu():
    m = InlineKeyboardMarkup(row_width=1)
    m.add(InlineKeyboardButton("🔍 Find Bot by ID", callback_data="search_by_id"), InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
    return m

def get_package_menu(bot_id):
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton("🧠 Auto Detect & Install", callback_data=f"pkg_auto:{bot_id}"))
    m.add(InlineKeyboardButton("📝 Manual Install (.txt)", callback_data=f"pkg_manual:{bot_id}"))
    return m

def get_control_panel(bot_id, is_running, p_type):
    m = InlineKeyboardMarkup(row_width=2)
    if is_running and p_type == "bot": m.add(InlineKeyboardButton("🛑 Stop", callback_data=f"stop:{bot_id}"), InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{bot_id}"))
    elif p_type == "bot": m.add(InlineKeyboardButton("▶️ Start", callback_data=f"start:{bot_id}"))
    
    m.add(InlineKeyboardButton("📜 Live Logs", callback_data=f"log:{bot_id}"), InlineKeyboardButton("📝 Instant Edit Code", callback_data=f"edit_code:{bot_id}"))
    if p_type == "web": m.add(InlineKeyboardButton("🌍 Public Web Link", callback_data=f"publink:{bot_id}"))
    m.add(InlineKeyboardButton("🗑️ Delete", callback_data=f"del:{bot_id}"), InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu"))
    return m

def get_admin_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(f"🛠 Maintenance: {'ON' if MAINTENANCE_MODE else 'OFF'}", callback_data="toggle_maintenance"), InlineKeyboardButton("🌐 All Bots Control", callback_data="list_all_bots"))
    m.add(InlineKeyboardButton("🚨 EMERGENCY KILL ALL", callback_data="emergency_kill"), InlineKeyboardButton("🧹 Purge Cache", callback_data="server_clean"))
    m.add(InlineKeyboardButton("📢 Broadcast Ad/Msg", callback_data="broadcast_menu"), InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu"))
    return m

# ==========================================
# 🚀 CORE DEPLOYMENT WORKFLOW
# ==========================================
def process_script_upload(message):
    uid = message.from_user.id
    if not message.document and not message.text: return
    
    bot_id = generate_bot_id()
    p_type = "bot"
    saved_path = ""

    msg = bot.send_message(message.chat.id, f"🔄 **Step 1: Saving Environment `{bot_id}`...**\n`[██░░░░░░░░] 20%`", parse_mode="Markdown")

    if message.text:
        code = message.text
        if "<html>" in code.lower() or "<?php" in code.lower():
            saved_path = os.path.join(TEMP_DIR, f"{bot_id}_index.html"); p_type = "web"
        else:
            saved_path = os.path.join(TEMP_DIR, f"{bot_id}_main.py"); p_type = "bot"
        with open(saved_path, "w", encoding="utf-8") as f: f.write(code)
    else:
        orig_fn = message.document.file_name
        file_info = bot.get_file(message.document.file_id)
        down = bot.download_file(file_info.file_path)
        
        if orig_fn.endswith('.zip'):
            zip_p = os.path.join(TEMP_DIR, orig_fn)
            with open(zip_p, "wb") as f: f.write(down)
            extract_dir = os.path.join(TEMP_DIR, bot_id)
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_p, 'r') as zip_ref: zip_ref.extractall(extract_dir)
            os.remove(zip_p)
            
            main_f = None
            for root, _, files in os.walk(extract_dir):
                for f in files:
                    if f in ['main.py', 'bot.py', 'app.py', 'index.html']:
                        main_f = os.path.join(root, f)
            if not main_f: return bot.edit_message_text("❌ `.zip` mein `main.py` ya `index.html` nahi mila!", message.chat.id, msg.message_id)
            saved_path = main_f
            p_type = "web" if saved_path.endswith(('.html', '.php')) else "bot"
        else:
            p_type = "web" if orig_fn.endswith(('.html', '.js', '.css', '.php')) else "bot"
            saved_path = os.path.join(TEMP_DIR, f"{bot_id}_{orig_fn}")
            with open(saved_path, "wb") as f: f.write(down)

    user_deploy_states[bot_id] = {"uid": uid, "path": saved_path, "type": p_type}
    
    if p_type == "web": 
        threading.Thread(target=finalize_deployment, args=(message.chat.id, msg.message_id, bot_id, "auto")).start()
    else:
        bot.edit_message_text(f"📦 **Identity Assigned:** `{bot_id}`\n\nAb batayein packages (dependencies) kaise install karne hain?", message.chat.id, msg.message_id, parse_mode="Markdown", reply_markup=get_package_menu(bot_id))

def finalize_deployment(chat_id, msg_id, bot_id, install_type, manual_req_path=None):
    state = user_deploy_states.get(bot_id)
    if not state: return
    uid, temp_path, p_type = state["uid"], state["path"], state["type"]
    
    final_folder = os.path.abspath(os.path.join(WEB_DIR if p_type == "web" else HOST_DIR, bot_id))
    os.makedirs(final_folder, exist_ok=True)
    final_path = os.path.join(final_folder, os.path.basename(temp_path))
    shutil.move(temp_path, final_path)
    
    animate_progress(chat_id, msg_id, "Syntax Security Check...", 40)
    if p_type == "bot":
        try: py_compile.compile(final_path, doraise=True)
        except py_compile.PyCompileError as e: return bot.edit_message_text(f"🛑 **Syntax Error!**\n`{e}`", chat_id, msg_id, parse_mode="Markdown")

        if install_type == "manual" and manual_req_path:
            animate_progress(chat_id, msg_id, "Installing Manual Requirements...", 60)
            subprocess.call([sys.executable, '-m', 'pip', 'install', '-r', manual_req_path, '--quiet'])
        else:
            animate_progress(chat_id, msg_id, "AST Smart Auto-Scan Active...", 60)
            needed = deep_analyze_imports(final_path)
            for idx, mod in enumerate(needed, start=1):
                pct = 60 + int((idx / len(needed)) * 30)
                animate_progress(chat_id, msg_id, f"Installing `{mod}`...", pct)
                subprocess.call([sys.executable, '-m', 'pip', 'install', mod, '--quiet'])

    animate_progress(chat_id, msg_id, "Finalizing Execution Sandbox...", 95)
    run_script_process(bot_id, final_path, uid, p_type)
    
    bot.edit_message_text(f"🚀 **Deployment 100% Successful!**\n\n📌 **Identity:** `{bot_id}`\n✅ **Status:** LIVE", chat_id, msg_id, parse_mode="Markdown", reply_markup=get_control_panel(bot_id, True, p_type))

# ==========================================
# 🤖 BOT CALLBACKS
# ==========================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if is_banned(uid): return
    user_chats.add(message.chat.id)
    bot.send_message(message.chat.id, f"⚡ **ULTRA-PRO HOSTING ENGINE** ⚡\n\n🆔 **Your ID:** `{uid}`\nUpload `.py`, `.zip`, `.html` or paste Code!", parse_mode="Markdown", reply_markup=get_user_menu(uid))

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    global MAINTENANCE_MODE
    uid = call.from_user.id
    chat = call.message.chat.id
    data = call.data
    user_chats.add(chat)

    if data == "main_menu": bot.edit_message_text("🎛️ **Main Dashboard:**", chat, call.message.message_id, reply_markup=get_user_menu(uid))
    elif data == "admin_panel" and is_admin(uid): bot.edit_message_text("👑 **Admin Master Controls:**", chat, call.message.message_id, reply_markup=get_admin_menu())
    elif data == "search_hub": bot.edit_message_text("🔍 **Identity Search Hub:**", chat, call.message.message_id, reply_markup=get_search_hub_menu())
    
    elif data == "host_file":
        if MAINTENANCE_MODE and not is_admin(uid): return bot.answer_callback_query(call.id, "Server Maintenance Active", show_alert=True)
        bot.send_message(chat, "📂 **Deploy:** Upload file OR paste your raw code here:")
        bot.register_next_step_handler(call.message, process_script_upload)
        
    elif data == "search_by_id":
        bot.send_message(chat, "🔍 Enter Bot ID (e.g., `BOT-1234`):", parse_mode="Markdown")
        bot.register_next_step_handler(call.message, lambda m: process_search_bot(m))

    elif data.startswith("pkg_auto:"):
        bot_id = data.split(":")[1]
        msg = bot.edit_message_text("🧠 Auto-Install Engine Started...", chat, call.message.message_id)
        threading.Thread(target=finalize_deployment, args=(chat, msg.message_id, bot_id, "auto")).start()
        
    elif data.startswith("pkg_manual:"):
        bot_id = data.split(":")[1]
        msg = bot.edit_message_text("📝 **Manual Installation:**\n\nSend `requirements.txt` OR type package names (e.g., `flask, requests`)", chat, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, lambda m: handle_manual_reqs(m, bot_id, msg.message_id))

    elif data in ["my_bots", "list_all_bots"]:
        if data == "list_all_bots" and not is_admin(uid): return
        m = InlineKeyboardMarkup(row_width=1)
        for bot_id, v in hosted_processes.items():
            if v["owner_id"] == uid or is_admin(uid):
                status = "🟢" if v["type"] == "web" or (v["process"] and v["process"].poll() is None) else "🔴"
                m.add(InlineKeyboardButton(f"{status} {bot_id} ({os.path.basename(v['path'])})", callback_data=f"manage:{bot_id}"))
        m.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.edit_message_text("🤖 **Managed Bots:**", chat, call.message.message_id, reply_markup=m)

    elif data.startswith("manage:"):
        bot_id = data.split(":")[1]
        if bot_id not in hosted_processes: return bot.answer_callback_query(call.id, "Project missing.", show_alert=True)
        proj = hosted_processes[bot_id]
        is_run = proj["process"] and proj["process"].poll() is None if proj["type"] == "bot" else True
        bot.edit_message_text(f"⚙️ **Control Panel:** `{bot_id}`", chat, call.message.message_id, parse_mode="Markdown", reply_markup=get_control_panel(bot_id, is_run, proj["type"]))

    elif data.startswith("edit_code:"):
        bot_id = data.split(":")[1]
        proj = hosted_processes[bot_id]
        bot.send_message(chat, f"📝 **Instant Edit Mode (`{bot_id}`):**\n\nPaste your new code below. Bot will overwrite and restart instantly.")
        bot.register_next_step_handler(call.message, lambda m: save_edited_code(m, bot_id, proj))

    elif data.startswith("log:"):
        bot_id = data.split(":")[1]
        log_path = os.path.join(LOG_DIR, f"{bot_id}.log")
        content = "No logs yet."
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as logf: content = logf.read()[-2500:] or content
        m = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Refresh Logs", callback_data=f"log:{bot_id}"), InlineKeyboardButton("🔙 Back", callback_data=f"manage:{bot_id}"))
        try: bot.edit_message_text(f"📜 **Live Logs (`{bot_id}`):**\n```text\n{content}\n```", chat, call.message.message_id, parse_mode="Markdown", reply_markup=m)
        except: bot.send_message(chat, f"📜 **Live Logs (`{bot_id}`):**\n```text\n{content}\n```", parse_mode="Markdown", reply_markup=m)

    elif data.startswith("stop:"): stop_script_process(data.split(":")[1]); bot.answer_callback_query(call.id, "🛑 Stopped!", show_alert=True)
    elif data.startswith("start:"): 
        b_id = data.split(":")[1]; run_script_process(b_id, hosted_processes[b_id]["path"], uid, hosted_processes[b_id]["type"])
        bot.answer_callback_query(call.id, "▶️ Started!", show_alert=True)
    elif data.startswith("restart:"): 
        b_id = data.split(":")[1]; stop_script_process(b_id); run_script_process(b_id, hosted_processes[b_id]["path"], uid, hosted_processes[b_id]["type"])
        bot.answer_callback_query(call.id, "🔄 Restarted!", show_alert=True)
        
    elif data.startswith("del:"): 
        b_id = data.split(":")[1]
        proj = hosted_processes.get(b_id)
        if proj:
            stop_script_process(b_id)
     
