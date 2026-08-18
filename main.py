import os, re, ast, time, sys, subprocess, threading, base64, py_compile, requests, zipfile, shutil, socket, random, json
from flask import Flask, abort
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
# 📂 SYSTEM DIRECTORIES & REGISTRY
# ==========================================
BASE_DIR = os.path.abspath(os.getcwd())
HOST_DIR = os.path.join(BASE_DIR, "hosted_env")
LOG_DIR = os.path.join(HOST_DIR, "logs")
TEMP_DIR = os.path.join(HOST_DIR, "temp_uploads")
REGISTRY_FILE = os.path.join(HOST_DIR, "engine_registry.json")

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
    "sklearn": "scikit-learn", "discord": "discord.py", "aiogram": "aiogram",
    "dotenv": "python-dotenv", "dateutil": "python-dateutil", "jwt": "PyJWT"
}
BUILTINS = sys.builtin_module_names

# ==========================================
# 🧠 BULLETPROOF PERSISTENCE & UTILITIES
# ==========================================
def save_registry():
    data = {bid: {"owner_id": p["owner_id"], "path": p["path"]} for bid, p in hosted_processes.items() if p["type"] == "bot"}
    try:
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)
    except: pass

def load_registry():
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for bid, info in data.items():
                    if os.path.exists(info["path"]):
                        run_script_process(bid, info["path"], info["owner_id"])
        except: pass

def is_admin(user_id): return int(user_id) == ADMIN_ID
def is_banned(user_id): return user_id in banned_users

def get_readable_uptime(seconds):
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {mins}m {secs}s"

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
# ⚙️ BULLETPROOF PROCESS MANAGER
# ==========================================
def run_script_process(bot_id, filepath, owner_id):
    abs_path = os.path.abspath(filepath)
    log_file_path = os.path.abspath(os.path.join(LOG_DIR, f"{bot_id}.log"))
    log_out = open(log_file_path, "a", encoding="utf-8")
    
    custom_env = os.environ.copy()
    if owner_id in user_custom_envs: custom_env.update(user_custom_envs[owner_id])
    
    proc = subprocess.Popen([sys.executable, abs_path], cwd=os.path.dirname(abs_path), stdout=log_out, stderr=log_out, env=custom_env, text=True)
    hosted_processes[bot_id] = {"process": proc, "owner_id": owner_id, "path": abs_path, "type": "bot", "start_time": time.time(), "log_file": log_file_path, "retries": 0}
    save_registry()

def stop_script_process(bot_id):
    if bot_id in hosted_processes:
        proc = hosted_processes[bot_id].get("process")
        if proc and proc.poll() is None:
            try: proc.terminate(); proc.wait(timeout=2)
            except: proc.kill()
        del hosted_processes[bot_id]
        save_registry()

def auto_healing_monitor():
    while True:
        time.sleep(15)
        for bot_id, data in list(hosted_processes.items()):
            proc = data["process"]
            owner_id = data["owner_id"]
            path = data["path"]
            
            if psutil and proc and proc.poll() is None:
                try:
                    p = psutil.Process(proc.pid)
                    if p.memory_info().rss > 1024 * 1024 * 1024: # 1GB RAM Limit
                        stop_script_process(bot_id)
                        bot.send_message(owner_id, f"🚨 **AUTO-KILL:** Bot `{bot_id}` exceeded 1GB RAM limit.")
                except: pass

            if proc and proc.poll() is not None and data.get("retries", 0) < 3:
                data["retries"] += 1
                run_script_process(bot_id, path, owner_id)

# ==========================================
# 🌐 KEEP-ALIVE WEB SERVER
# ==========================================
@app.route('/')
def home():
    active_count = len([p for p in hosted_processes.values() if p["process"] and p["process"].poll() is None])
    return f"⚡ Bulletproof Python Cloud Engine is Live! Active Bots: {active_count}"

# ==========================================
# 🎛️ 5-MENU PROFESSIONAL UI ECOSYSTEM
# ==========================================
def get_user_menu(user_id):
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton("🚀 Deploy Python Bot", callback_data="host_file"), InlineKeyboardButton("🤖 My Managed Bots", callback_data="my_bots"))
    m.add(InlineKeyboardButton("🔍 Search Bot ID", callback_data="search_hub"), InlineKeyboardButton("📊 Server Health", callback_data="server_ping"))
    if is_admin(user_id): m.add(InlineKeyboardButton("👑 Master Admin Control", callback_data="admin_panel"))
    return m

def get_search_hub_menu():
    m = InlineKeyboardMarkup(row_width=1)
    m.add(InlineKeyboardButton("🔍 Find Bot by ID", callback_data="search_by_id"), InlineKeyboardButton("📋 List My Bot IDs", callback_data="list_my_ids"), InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
    return m

def get_control_panel(bot_id, is_running):
    m = InlineKeyboardMarkup(row_width=2)
    if is_running: m.add(InlineKeyboardButton("🛑 Stop", callback_data=f"stop:{bot_id}"), InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{bot_id}"))
    else: m.add(InlineKeyboardButton("▶️ Start", callback_data=f"start:{bot_id}"))
    
    m.add(InlineKeyboardButton("📜 Live Logs", callback_data=f"log:{bot_id}"), InlineKeyboardButton("📝 Instant Edit Code", callback_data=f"edit_code:{bot_id}"))
    m.add(InlineKeyboardButton("🗑️ Delete Bot", callback_data=f"del:{bot_id}"), InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu"))
    return m

def get_package_menu(bot_id):
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton("🧠 Auto Detect & Install", callback_data=f"pkg_auto:{bot_id}"))
    m.add(InlineKeyboardButton("📝 Manual Install (.txt)", callback_data=f"pkg_manual:{bot_id}"))
    return m

def get_admin_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton("🌐 Global Node Manager", callback_data="list_all_bots"), InlineKeyboardButton("📢 Smart Broadcast & Ads", callback_data="admin_broadcast"))
    m.add(InlineKeyboardButton("🚫 Ban / Unban User", callback_data="admin_ban_menu"), InlineKeyboardButton("📊 Server Diagnostics", callback_data="server_health"))
    m.add(InlineKeyboardButton("🚨 DEFCON 1 (Kill All)", callback_data="emergency_kill"), InlineKeyboardButton("🧹 Deep Server Clean", callback_data="server_clean"))
    m.add(InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu"))
    return m

# ==========================================
# 🚀 DEPLOYMENT PIPELINE
# ==========================================
def process_script_upload(message):
    uid = message.from_user.id
    if not message.document and not message.text: return
    
    bot_id = generate_bot_id()
    saved_path = ""
    msg = bot.send_message(message.chat.id, f"🔄 Initializing sandbox for `{bot_id}`...", parse_mode="Markdown")

    if message.text:
        saved_path = os.path.join(TEMP_DIR, f"{bot_id}_main.py")
        with open(saved_path, "w", encoding="utf-8") as f: f.write(message.text)
    else:
        orig_fn = message.document.file_name
        if not orig_fn.endswith(('.py', '.zip')):
            return bot.edit_message_text("❌ Only `.py` or `.zip` files are supported!", message.chat.id, msg.message_id)
            
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
                    if f in ['main.py', 'bot.py', 'app.py']: main_f = os.path.join(root, f)
            if not main_f: return bot.edit_message_text("❌ `main.py` not found inside ZIP!", message.chat.id, msg.message_id)
            saved_path = main_f
        else:
            saved_path = os.path.join(TEMP_DIR, f"{bot_id}_{orig_fn}")
            with open(saved_path, "wb") as f: f.write(down)

    user_deploy_states[bot_id] = {"uid": uid, "path": saved_path}
    bot.edit_message_text(f"📦 **Identity Assigned:** `{bot_id}`\n\nChoose dependency installation method:", message.chat.id, msg.message_id, parse_mode="Markdown", reply_markup=get_package_menu(bot_id))

def finalize_deployment(chat_id, msg_id, bot_id, install_type, manual_req_path=None):
    state = user_deploy_states.get(bot_id)
    if not state: return
    uid, temp_path = state["uid"], state["path"]
    
    final_folder = os.path.abspath(os.path.join(HOST_DIR, bot_id))
    os.makedirs(final_folder, exist_ok=True)
    final_path = os.path.join(final_folder, os.path.basename(temp_path))
    
    if os.path.abspath(temp_path) != os.path.abspath(final_path):
        shutil.move(temp_path, final_path)
    
    try: py_compile.compile(final_path, doraise=True)
    except py_compile.PyCompileError as e: return bot.edit_message_text(f"🛑 **Syntax Error:**\n`{e}`", chat_id, msg_id, parse_mode="Markdown")

    if install_type == "manual" and manual_req_path:
        bot.edit_message_text(f"⚙️ Installing manual requirements for `{bot_id}`...", chat_id, msg_id)
        subprocess.call([sys.executable, '-m', 'pip', 'install', '-r', manual_req_path, '--quiet'])
    else:
        bot.edit_message_text(f"🧠 Scanning & auto-installing packages for `{bot_id}`...", chat_id, msg_id)
        needed = deep_analyze_imports(final_path)
        for mod in needed:
            subprocess.call([sys.executable, '-m', 'pip', 'install', mod, '--quiet'])

    run_script_process(bot_id, final_path, uid)
    bot.edit_message_text(f"🚀 **Deployment Successful!**\n\n📌 **Identity:** `{bot_id}`\n✅ **Status:** LIVE 24/7", chat_id, msg_id, parse_mode="Markdown", reply_markup=get_control_panel(bot_id, True))

# ==========================================
# 🤖 BOT HANDLERS & CALLBACKS
# ==========================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if is_banned(uid): return bot.send_message(uid, "🚫 You are banned from this engine.")
    user_chats.add(message.chat.id)
    bot.send_message(message.chat.id, f"⚡ **BULLETPROOF PYTHON CLOUD ENGINE** ⚡\n\n🆔 **Your ID:** `{uid}`\nDeploy and control Python bots securely.", parse_mode="Markdown", reply_markup=get_user_menu(uid))

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid = call.from_user.id
    chat = call.message.chat.id
    data = call.data
    user_chats.add(chat)

    if data == "main_menu": bot.edit_message_text("🎛️ **Main Dashboard:**", chat, call.message.message_id, reply_markup=get_user_menu(uid))
    elif data == "admin_panel" and is_admin(uid): bot.edit_message_text("👑 **Master Admin Center (God Mode):**", chat, call.message.message_id, reply_markup=get_admin_menu())
    elif data == "search_hub": bot.edit_message_text("🔍 **Identity Search Hub:**", chat, call.message.message_id, reply_markup=get_search_hub_menu())
    
    elif data == "host_file":
        bot.send_message(chat, "📂 **Deploy:** Upload your `.py` file, `.zip`, or paste code below:")
        bot.register_next_step_handler(call.message, process_script_upload)
        
    elif data == "search_by_id":
        bot.send_message(chat, "🔍 Enter Bot ID (e.g., `BOT-1234`):", parse_mode="Markdown")
        bot.register_next_step_handler(call.message, lambda m: process_search_bot(m))

    elif data == "list_my_ids":
        my_ids = [b for b, v in hosted_processes.items() if v["owner_id"] == uid]
        bot.send_message(chat, f"📋 **Your Active IDs:**\n" + (", ".join(my_ids) if my_ids else "None"), parse_mode="Markdown")

    elif data.startswith("pkg_auto:"):
        bot_id = data.split(":")[1]
        msg = bot.edit_message_text("🧠 Auto-Install Pipeline Active...", chat, call.message.message_id)
        threading.Thread(target=finalize_deployment, args=(chat, msg.message_id, bot_id, "auto")).start()
        
    elif data.startswith("pkg_manual:"):
        bot_id = data.split(":")[1]
        msg = bot.edit_message_text("📝 **Manual Installation:**\n\nSend `requirements.txt` OR type package names separated by commas:", chat, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, lambda m: handle_manual_reqs(m, bot_id, msg.message_id))

    elif data in ["my_bots", "list_all_bots"]:
        m = InlineKeyboardMarkup(row_width=1)
        for bot_id, v in hosted_processes.items():
            if v["owner_id"] == uid or is_admin(uid):
                status = "🟢" if v["process"] and v["process"].poll() is None else "🔴"
                m.add(InlineKeyboardButton(f"{status} {bot_id} (Owner: {v['owner_id']})", callback_data=f"manage:{bot_id}"))
        m.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu" if not is_admin(uid) else "admin_panel"))
        bot.edit_message_text("🤖 **Managed Nodes:**", chat, call.message.message_id, reply_markup=m)

    elif data.startswith("manage:"):
        bot_id = data.split(":")[1]
        if bot_id not in hosted_processes: return bot.answer_callback_query(call.id, "Node missing.", show_alert=True)
        proj = hosted_processes[bot_id]
        is_run = proj["process"] and proj["process"].poll() is None
        bot.edit_message_text(f"⚙️ **Control Panel:** `{bot_id}`", chat, call.message.message_id, parse_mode="Markdown", reply_markup=get_control_panel(bot_id, is_run))

    elif data.startswith("edit_code:"):
        bot_id = data.split(":")[1]
        proj = hosted_processes[bot_id]
        bot.send_message(chat, f"📝 **Instant Edit Mode (`{bot_id}`):**\n\nPaste your new Python code below to overwrite and restart instantly.")
        bot.register_next_step_handler(call.message, lambda m: save_edited_code(m, bot_id, proj))

    elif data.startswith("log:"):
        bot_id = data.split(":")[1]
        log_path = os.path.join(LOG_DIR, f"{bot_id}.log")
        content = "No logs yet."
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as logf: content = logf.read()[-2000:]
        m = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Refresh", callback_data=f"log:{bot_id}"), InlineKeyboardButton("🔙 Back", callback_data=f"manage:{bot_id}"))
        bot.edit_message_text(f"📜 **Logs (`{bot_id}`):**\n```text\n{content}\n```", chat, call.message.message_id, parse_mode="Markdown", reply_markup=m)

    elif data.startswith("stop:"): stop_script_process(data.split(":")[1]); bot.answer_callback_query(call.id, "🛑 Stopped!", show_alert=True)
    elif data.startswith("start:"): 
        b_id = data.split(":")[1]; run_script_process(b_id, hosted_processes[b_id]["path"], hosted_processes[b_id]["owner_id"])
        bot.answer_callback_query(call.id, "▶️ Started!", show_alert=True)
    elif data.startswith("restart:"): 
        b_id = data.split(":")[1]; stop_script_process(b_id); run_script_process(b_id, hosted_processes[b_id]["path"], hosted_processes[b_id]["owner_id"])
        bot.answer_callback_query(call.id, "🔄 Restarted!", show_alert=True)
        
    elif data.startswith("del:"): 
        b_id = data.split(":")[1]
        proj = hosted_processes.get(b_id)
        if proj:
            stop_script_process(b_id)
            try: shutil.rmtree(os.path.dirname(proj["path"]), ignore_errors=True)
            except: pass
        bot.edit_message_text(f"🗑️ `{b_id}` deleted.", chat, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu")))

    elif data == "server_ping":
        ram = psutil.virtual_memory().percent if psutil else "N/A"
        cpu = psutil.cpu_percent(interval=0.5) if psutil else "N/A"
        bot.send_message(chat, f"📡 **Status:** Optimal\n⏱️ **Uptime:** `{get_readable_uptime(time.time() - engine_start_time)}`\n💾 **RAM Use:** `{ram}%`\n⚡ **CPU Use:** `{cpu}%`", parse_mode="Markdown")
    elif data == "server_clean" and is_admin(uid):
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        os.makedirs(TEMP_DIR, exist_ok=True)
        bot.send_message(chat, "🧹 **Temporary cache cleaned successfully!**")
    elif data == "emergency_kill" and is_admin(uid):
        for b_id in list(hosted_processes.keys()): stop_script_process(b_id)
        bot.send_message(chat, "🚨 **DEFCON 1: ALL NODES KILLED!**", parse_mode="Markdown")
    elif data == "admin_broadcast" and is_admin(uid):
        bot.send_message(chat, "📢 **Send Announcement/Ad (Text, Photo, Video, File):**")
        bot.register_next_step_handler(call.message, process_broadcast)
    elif data == "admin_ban_menu" and is_admin(uid):
        bot.send_message(chat, "🚫 **Send User ID to Ban/Unban:**\n(e.g., `123456789`)", parse_mode="Markdown")
        bot.register_next_step_handler(call.message, process_ban_user)

# ==========================================
# 🧩 HELPERS & ADMIN ACTIONS
# ==========================================
def handle_manual_reqs(message, bot_id, msg_id):
    req_path = os.path.join(TEMP_DIR, f"req_{bot_id}.txt")
    if message.text:
        with open(req_path, "w") as f: f.write(message.text.replace(",", "\n"))
    elif message.document:
        f_info = bot.get_file(message.document.file_id)
        with open(req_path, "wb") as f: f.write(bot.download_file(f_info.file_path))
    threading.Thread(target=finalize_deployment, args=(message.chat.id, msg_id, bot_id, "manual", req_path)).start()

def process_search_bot(message):
    query = message.text.strip().upper()
    if not query.startswith("BOT-"): query = f"BOT-{query}"
    if query in hosted_processes:
        p = hosted_processes[query]
        is_run = p["
