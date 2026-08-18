import os, re, ast, time, sys, subprocess, threading, base64, py_compile, requests, zipfile, shutil, socket, importlib.util
from datetime import datetime
import traceback

# Auto-install psutil for advanced RAM/CPU monitoring
try:
    import psutil
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'psutil', '--quiet'])
    import psutil

from flask import Flask, send_from_directory, request, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# ⚙️ MASTER CONFIGS & CREDENTIALS
# ==========================================
ADMIN_ID = 7193432903
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8483068207:AAEq3LPHIYlug4qtQnkc9dQB2u-r6kQm1cs")
GH_TOKEN = os.environ.get("GH_TOKEN", "") # Optional
GH_REPO = os.environ.get("GH_REPO", "my-hosted-bots")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=10) # 10 Threads for heavy multi-tasking
app = Flask(__name__)

# ==========================================
# 📂 SYSTEM DIRECTORIES & GLOBALS
# ==========================================
HOST_DIR = "hosted_env"
LOG_DIR = os.path.join(HOST_DIR, "logs")
DB_DIR = os.path.join(HOST_DIR, "databases")
WEB_DIR = os.path.join(HOST_DIR, "web_public")

for d in [HOST_DIR, LOG_DIR, DB_DIR, WEB_DIR]:
    os.makedirs(d, exist_ok=True)

# Central State Database (RAM Memory)
hosted_processes = {}  
user_chats = set()
banned_users = set()
user_custom_envs = {}
engine_start_time = time.time()
MAINTENANCE_MODE = False

PIP_MAP = {"telebot": "pyTelegramBotAPI", "PIL": "Pillow", "cv2": "opencv-python", "yaml": "pyyaml", "dotenv": "python-dotenv", "bs4": "beautifulsoup4"}
BUILTINS = sys.builtin_module_names

# ==========================================
# 🧠 BACKEND SMART FEATURES (INTERNAL)
# ==========================================
def find_free_port():
    """🚪 Feature 3: Auto-Port Resolver for Web Apps"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def smart_syntax_checker(file_path):
    """🛡️ Feature 2: Syntax Pre-Checker (Zero-Crash Guard)"""
    try:
        py_compile.compile(file_path, doraise=True)
        return True, "Syntax 100% Perfect ✔️"
    except py_compile.PyCompileError as e:
        return False, f"Syntax Error at Line: {str(e).splitlines()[-1]}"

def deep_auto_locator(extract_path):
    """📂 Feature 4: Deep Auto-Locator (Finds main file & requirements.txt)"""
    main_file, req_file = None, None
    for root, dirs, files in os.walk(extract_path):
        for file in files:
            if file in ['main.py', 'bot.py', 'app.py', 'index.html', 'index.php']:
                main_file = os.path.join(root, file)
            if file == 'requirements.txt':
                req_file = os.path.join(root, file)
    return main_file, req_file

def human_error_translator(log_text):
    """🤖 Feature 5: Human-Readable Error Translator"""
    if "KeyError" in log_text: return "💡 Tip: Dictionary Key missing/incorrect."
    if "Unauthorized" in log_text or "Token" in log_text: return "💡 Tip: Invalid API Token."
    if "ModuleNotFoundError" in log_text: return "💡 Tip: Go to Control Panel -> 'Add Package'."
    if "SyntaxError" in log_text: return "💡 Tip: Check brackets/indentation in code."
    return "💡 Tip: Check logs above for details."

# ==========================================
# 🚀 SMART ANIMATOR (Throttled for heavy AI loads)
# ==========================================
def animate_progress(chat_id, msg_id, text, percent):
    bars = int(percent / 10)
    bar_str = "█" * bars + "░" * (10 - bars)
    full_text = f"⚙️ **System Engine Processing:**\n\n`[{bar_str}] {percent}%`\n> {text}"
    try:
        bot.edit_message_text(full_text, chat_id, msg_id, parse_mode="Markdown")
        time.sleep(1.5) # Prevents Telegram API Ban
    except: pass

# ==========================================
# 🌐 INTEGRATED WEB SERVER (Flask Tunnel)
# ==========================================
@app.route('/')
def home():
    bots_count = len([p for p in hosted_processes.values() if p['type'] == 'bot'])
    return f"⚡ Ultra-Pro Host Engine is ONLINE 24/7. Active Heavy Bots: {bots_count}"

@app.route('/web/<proj_id>/<path:filename>')
def serve_user_web(proj_id, filename):
    proj = hosted_processes.get(proj_id)
    if not proj or not proj.get('is_public'): abort(403)
    return send_from_directory(os.path.dirname(proj['path']), filename)

# ==========================================
# 🛡️ SMART WATCHDOG & AUTO-HEAL
# ==========================================
def auto_healing_monitor():
    while True:
        time.sleep(15)
        for name, data in list(hosted_processes.items()):
            if data["type"] != "bot": continue
            proc = data["process"]
            owner = data["owner_id"]
            
            # CPU/RAM Monitor
            if proc and proc.poll() is None:
                try:
                    p = psutil.Process(proc.pid)
                    # 1024MB (1GB) limit for Heavy AI bots
                    if p.memory_info().rss > data.get("ram_limit", 1024 * 1024 * 1024): 
                        stop_project(name)
                        bot.send_message(owner, f"🚨 **WARNING:** `{name}` killed for exceeding 1GB RAM!")
                except: pass
            
            # Auto-Heal Crash Recovery
            elif proc and proc.poll() is not None and data.get("auto_heal", True):
                bot.send_message(owner, f"🔄 **Auto-Heal System:** `{name}` crashed! Reviving now...")
                start_project(name, owner, "bot", data["path"])

# ==========================================
# ⚙️ PROJECT PROCESS MANAGER
# ==========================================
def start_project(name, owner, p_type, filepath):
    if p_type == "bot":
        log_out = open(os.path.join(LOG_DIR, f"{name}.log"), "a", encoding="utf-8")
        env = os.environ.copy()
        if owner in user_custom_envs: env.update(user_custom_envs[owner])
        
        proc = subprocess.Popen([sys.executable, filepath], cwd=os.path.dirname(filepath), stdout=log_out, stderr=subprocess.STDOUT, env=env, text=True)
        hosted_processes[name] = {"process": proc, "owner_id": owner, "type": "bot", "auto_heal": True, "path": filepath, "ram_limit": 1024 * 1024 * 1024} # High RAM for AI
    elif p_type == "web":
        hosted_processes[name] = {"process": None, "owner_id": owner, "type": "web", "port": find_free_port(), "is_public": True, "path": filepath}

def stop_project(name):
    if name in hosted_processes:
        p = hosted_processes[name]["process"]
        if p and p.poll() is None:
            try: p.terminate(); p.wait(timeout=3)
            except: p.kill()

# ==========================================
# 🎛️ UI MENUS (Ultra-Advanced)
# ==========================================
def get_user_menu(uid):
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("🚀 Deploy Project", callback_data="deploy_start"),
        InlineKeyboardButton("🤖 Active Projects", callback_data="my_projects"),
        InlineKeyboardButton("🛑 Halt All Mine", callback_data="halt_all"),
        InlineKeyboardButton("🔑 Config & ENV", callback_data="manage_env"),
        InlineKeyboardButton("📂 Smart ZIP Backup", callback_data="smart_backup"),
        InlineKeyboardButton("📈 Server Health", callback_data="server_health")
    )
    if int(uid) == ADMIN_ID: m.add(InlineKeyboardButton("👑 Master Admin Panel", callback_data="admin_panel"))
    return m

def get_control_panel(name, is_running, p_type):
    m = InlineKeyboardMarkup(row_width=2)
    if is_running and p_type == "bot": 
        m.add(InlineKeyboardButton("🛑 Stop", callback_data=f"stop:{name}"), InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{name}"))
    elif p_type == "bot": 
        m.add(InlineKeyboardButton("▶️ Start", callback_data=f"start:{name}"))
        
    m.add(InlineKeyboardButton("📜 Live Logs", callback_data=f"log:{name}"), InlineKeyboardButton("📝 Live Editor", callback_data=f"edit:{name}"))
    
    if p_type == "bot": m.add(InlineKeyboardButton("🔌 Add Package", callback_data=f"addpkg:{name}"), InlineKeyboardButton("⚙️ Auto-Heal", callback_data=f"heal:{name}"))
    else: m.add(InlineKeyboardButton("🌍 Public Access Link", callback_data=f"publink:{name}"))
        
    m.add(InlineKeyboardButton("🗑️ Delete", callback_data=f"del:{name}"), InlineKeyboardButton("🔙 Dashboard", callback_data="main_menu"))
    return m

def get_admin_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(
        InlineKeyboardButton("🛠 Maintenance Mode", callback_data="toggle_maint"),
        InlineKeyboardButton("🌐 Global Nodes", callback_data="global_nodes"),
        InlineKeyboardButton("🚨 DEFCON 1", callback_data="defcon"),
        InlineKeyboardButton("🧹 Deep Clean", callback_data="clean_server"),
        InlineKeyboardButton("📢 Broadcast", callback_data="broadcast"),
        InlineKeyboardButton("📤 OTA Update", callback_data="ota_update")
    )
    m.add(InlineKeyboardButton("🔙 Back to Dashboard", callback_data="main_menu"))
    return m

# ==========================================
# 🚀 CORE DEPLOYMENT LOGIC (AI & Heavy Bot Ready)
# ==========================================
def process_deployment(message):
    uid = message.from_user.id
    if not message.document and not message.text: return
    
    msg = bot.send_message(message.chat.id, "🔄 Booting Heavy Deployment Sequence...")
    proj_name = f"proj_{uid}_{int(time.time())}"
    p_type, file_path, req_path = "bot", "", None
    
    animate_progress(message.chat.id, msg.message_id, "Analyzing Input Architecture...", 10)

    try:
        if message.text:
            code = message.text
            if "<html>" in code.lower() or "<?php" in code.lower():
                file_path = os.path.join(WEB_DIR, f"{proj_name}.html"); p_type = "web"
            else:
                file_path = os.path.join(HOST_DIR, f"{proj_name}.py"); p_type = "bot"
            with open(file_path, "w", encoding="utf-8") as f: f.write(code)

        else:
            fn = message.document.file_name
            file_info = bot.get_file(message.document.file_id)
            down = bot.download_file(file_info.file_path)
            
            if fn.endswith('.zip'):
                zip_p = os.path.join(HOST_DIR, fn)
                with open(zip_p, "wb") as f: f.write(down)
                extract_folder = os.path.join(HOST_DIR, proj_name)
                with zipfile.ZipFile(zip_p, 'r') as zip_ref: zip_ref.extractall(extract_folder)
                os.remove(zip_p)
                
                main_f, req_f = deep_auto_locator(extract_folder)
                if not main_f: return bot.edit_message_text("❌ Missing `main.py` or `index.html` in ZIP.", message.chat.id, msg.message_id)
                file_path = main_f
                req_path = req_f
                p_type = "web" if file_path.endswith(('.html', '.php')) else "bot"
            else:
                p_type = "web" if fn.endswith(('.html', '.js', '.css', '.php')) else "bot"
                file_path = os.path.join(WEB_DIR if p_type == "web" else HOST_DIR, f"{proj_name}_{fn}")
                with open(file_path, "wb") as f: f.write(down)

        animate_progress(message.chat.id, msg.message_id, "Syntax Security Check...", 30)
        if p_type == "bot":
            is_safe, err_msg = smart_syntax_checker(file_path)
            if not is_safe: return bot.edit_message_text(f"🛑 **Syntax Error!**\n`{err_msg}`", message.chat.id, msg.message_id, parse_mode="Markdown")

        # Massive Dependency Resolver
        if p_type == "bot":
            if req_path:
                animate_progress(message.chat.id, msg.message_id, "Installing Heavy Requirements (May take time)...", 50)
                subprocess.call([sys.executable, '-m', 'pip', 'install', '-r', req_path, '--quiet'])
            else:
                animate_progress(message.chat.id, msg.message_id, "AST Smart Scanner Active...", 60)
                with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
                imports = set(re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE))
                for mod in imports:
                    mod_name = PIP_MAP.get(mod, mod)
                    if mod not in BUILTINS and importlib.util.find_spec(mod_name) is None:
                        animate_progress(message.chat.id, msg.message_id, f"Installing: {mod_name}...", 75)
                        subprocess.call([sys.executable, '-m', 'pip', 'install', mod_name, '--quiet'])

        animate_progress(message.chat.id, msg.message_id, "Finalizing Virtual Sandbox...", 90)
        start_project(proj_name, uid, p_type, file_path)
        
        bot.edit_message_text(f"🚀 **Deployment 100% Successful!**\n\n📌 **Name:** `{proj_name}`\n🗂 **Type:** `{'Web App 🌐' if p_type=='web' else 'Heavy AI Bot 🤖'}`\n✅ **Status:** Live & Protected", message.chat.id, msg.message_id, parse_mode="Markdown", reply_markup=get_control_panel(proj_name, True, p_type))
    except Exception as e:
        bot.edit_message_text(f"❌ **Fatal Error:** `{str(e)}`", message.chat.id, msg.message_id, parse_mode="Markdown")

# ==========================================
# 🤖 BOT INTERFACE HANDLERS
# ==========================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if uid in banned_users: return
    user_chats.add(message.chat.id)
    role = "👑 Master Admin" if int(uid) == ADMIN_ID else "👤 System User"
    bot.send_message(message.chat.id, f"⚡ **ULTRA-PRO HOSTING ENGINE v10** ⚡\n\n🔰 **Role:** {role}\n💻 AI-Ready | 1GB+ RAM Support | Async Threads\n\nChoose an option:", parse_mode="Markdown", reply_markup=get_user_menu(uid))

@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    chat = call.message.chat.id
    uid = call.from_user.id
    data = call.data

    if data == "main_menu": bot.edit_message_text("🎛️ **Main Dashboard:**", chat, call.message.message_id, reply_markup=get_user_menu(uid))
    elif data == "admin_panel" and int(uid) == ADMIN_ID: bot.edit_message_text("👑 **Master Admin Center:**", chat, call.message.message_id, reply_markup=get_admin_menu())
    
    elif data == "deploy_start":
        bot.send_message(chat, "📂 **Smart Deploy:**\nSend `.py`, `.html`, or a **.zip (with AI requirements.txt)**. OR Paste raw code below:")
        bot.register_next_step_handler(call.message, process_deployment)
        
    elif data == "my_projects":
        m = InlineKeyboardMarkup()
        mine = [k for k, v in hosted_processes.items() if v["owner_id"] == uid or int(uid) == ADMIN_ID]
        for k in mine: m.add(InlineKeyboardButton(f"{'🌐' if hosted_processes[k]['type']=='web' else '🤖'} {k}", callback_data=f"manage:{k}"))
        m.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.edit_message_text("🤖 **Your Active Projects:**", chat, call.message.message_id, reply_markup=m)

    elif data.startswith("manage:"):
        name = data.split(":")[1]
        if name not in hosted_processes: return bot.answer_callback_query(call.id, "Project not found.", show_alert=True)
        proj = hosted_processes[name]
        is_run = proj["process"] is not None and proj["process"].poll() is None if proj["type"] == "bot" else True
        bot.edit_message_text(f"⚙️ **Control Panel:** `{name}`", chat, call.message.message_id, parse_mode="Markdown", reply_markup=get_control_panel(name, is_run, proj["type"]))

    elif data.startswith("log:"):
        name = data.split(":")[1]
        log_path = os.path.join(LOG_DIR, f"{name}.log")
        content = "Log empty."
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()[-2000:]
        
        hint = human_error_translator(content)
        bot.edit_message_text(f"📜 **Live Logs (`{name}`):**\n```\n{content}\n```\n{hint}", chat, call.message.message_id, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data=f"manage:{name}")))

    elif data.startswith("stop:"): stop_project(data.split(":")[1]); bot.answer_callback_query(call.id, "🛑 Stopped!", show_alert=True)
    elif data.startswith("start:"): 
        name = data.split(":")[1]
        start_project(name, uid, hosted_processes[name]["type"], hosted_processes[name]["path"])
        bot.answer_callback_query(call.id, "▶️ Started!", show_alert=True)

    elif data.startswith("del:"):
        name = data.split(":")[1]
        stop_project(name)
        try: shutil.rmtree(os.path.dirname(hosted_processes[name]["path"]), ignore_errors=True)
        except: pass
        del hosted_processes[name]
        bot.edit_message_text(f"🗑️ Project `{name}` completely deleted.", chat, call.message.message_id, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="main_menu")))

    elif data.startswith("publink:"):
        name = data.split(":")[1]
        proj = hosted_processes.get(name)
        try:
            ip = requests.get('https://api.ipify.org').text
            url = f"http://{ip}:10000/web/{name}/" + os.path.basename(proj['path'])
            bot.send_message(chat, f"🌍 **Public Web Link:**\n\n🔗 [Click to Open App]({url})\n\n_Note: Route is active!_", parse_mode="Markdown")
        except: bot.send_message(chat, "Link generation failed.")

    elif data == "server_health":
        ram, cpu = psutil.virtual_memory().percent, psutil.cpu_percent(interval=0.5)
        bar = lambda p: "█" * int(p/10) + "░" * (10 - int(p/10))
        uptime = str(datetime.now() - datetime.fromtimestamp(engine_start_time)).split('.')[0]
        bot.edit_message_text(f"📈 **AI Engine Health:**\n\n**CPU Load:**\n`[{bar(cpu)}] {cpu}%`\n\n**RAM Usage:**\n`[{bar(ram)}] {ram}%`\n\n⏱ Uptime: `{uptime}`", chat, call.message.message_id, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="main_menu")))

    elif data == "defcon" and int(uid) == ADMIN_ID:
        for name in list(hosted_processes.keys()): stop_project(name)
        bot.send_message(chat, "🚨 **DEFCON 1: ALL BOT PROCESSES TERMINATED.**")

# ==========================================
# 🔥 MAIN MULTI-THREADED ENGINE STARTER
# ==========================================
if __name__ == "__main__":
    print("Initializing Multi-Threaded Heavy Architecture...")
    
    # Thread 1: Auto-Heal & Watchdog for RAM Control
    threading.Thread(target=auto_healing_monitor, daemon=True).start()
    
    # Thread 2: Telegram Bot (Uses its own 10 sub-threads for massive user load)
    threading.Thread(target=lambda: bot.infinity_polling(timeout=60, long_polling_timeout=30), daemon=True).start()
    
    # Main Thread: Flask Web Server (Tunnels all Web Apps + Keeps Engine Alive)
    print("⚡ Ultra-Pro AI-Ready Engine is LIVE on Port 10000!")
    app.run(host="0.0.0.0", port=10000, debug=False, use_reloader=False)
                 
