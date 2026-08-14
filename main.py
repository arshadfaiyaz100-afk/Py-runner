import os
import re
import time
import subprocess
import threading
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Environment Variable से टोकन लें या सीधे यहाँ डालें
TOKEN = os.environ.get("BOT_TOKEN", "8483068207:AAEq3LPHIYlug4qtQnkc9dQB2u-r6kQm1cs")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Global variables
running_process = None
active_filename = None
start_time = 0

@app.route('/')
def home():
    return "Ultra-Pro Master Bot Host is Live 24/7!"

# Control Menu
def get_control_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🚀 Host New .py File", callback_data="host_file"),
        InlineKeyboardButton("📦 Host requirements.txt", callback_data="host_req"),
        InlineKeyboardButton("📊 Live Status & Uptime", callback_data="status"),
        InlineKeyboardButton("🛑 Stop Script", callback_data="stop_bot"),
        InlineKeyboardButton("🔄 Restart Script", callback_data="restart_bot")
    )
    return markup

# Function to extract required modules from python script
def extract_requirements(file_path):
    installed_modules = set()
    builtins = {'os', 'sys', 'time', 'math', 're', 'subprocess', 'threading', 'json', 'random', 'datetime', 'urllib'}
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    # Find all 'import xyz' or 'from xyz import ...'
    imports = re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE)
    
    for mod in imports:
        if mod not in builtins:
            installed_modules.add(mod)
            
    return list(installed_modules)

# Function to auto pip install missing modules
def auto_install_packages(modules, chat_id, progress_msg):
    if not modules:
        return True
    
    for mod in modules:
        try:
            bot.edit_message_text(f"📦 **Auto-Installing Dependency:** `{mod}`...\n`[██████░░░░] 60%`", 
                                  chat_id, progress_msg.message_id, parse_mode="Markdown")
            subprocess.check_call(['python', '-m', 'pip', 'install', mod])
        except Exception as e:
            # Some module names differ from pip package names, continue anyway
            pass
    return True

@bot.message_handler(commands=['start'])
def start_command(message):
    welcome_msg = (
        "⚡ **ULTRA-PRO PYTHON BOT HOSTING ENGINE** ⚡\n\n"
        "Send me any Python script (`.py`), and I will:\n"
        "1. 🔍 Scan for required libraries.\n"
        "2. 📦 Automatically `pip install` missing packages.\n"
        "3. 🚀 Host and run it 24/7 in background!\n\n"
        "👇 **Select an option below:**"
    )
    bot.send_message(message.chat.id, welcome_msg, parse_mode="Markdown", reply_markup=get_control_menu())

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    global running_process, active_filename

    if call.data == "host_file":
        bot.send_message(chat_id, "📂 **Send your `.py` script file now.**")
        bot.register_next_step_handler(call.message, process_uploaded_file)

    elif call.data == "host_req":
        bot.send_message(chat_id, "📜 **Send your `requirements.txt` file now.**")
        bot.register_next_step_handler(call.message, process_requirements_file)

    elif call.data == "status":
        if running_process and running_process.poll() is None:
            uptime = int(time.time() - start_time)
            bot.send_message(chat_id, f"🟢 **Status:** Active & Running\n📁 **Script:** `{active_filename}`\n⏱️ **Uptime:** {uptime} seconds", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "🔴 **Status:** Offline / No script running right now.")

    elif call.data == "stop_bot":
        if running_process and running_process.poll() is None:
            running_process.terminate()
            running_process = None
            bot.send_message(chat_id, "🛑 **Script Stopped Successfully.** Memory cleared.")
        else:
            bot.send_message(chat_id, "⚠️ No script is currently active.")

    elif call.data == "restart_bot":
        if active_filename and os.path.exists(active_filename):
            bot.send_message(chat_id, "🔄 **Restarting active script...**")
            if running_process:
                running_process.terminate()
            running_process = subprocess.Popen(['python', active_filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            bot.send_message(chat_id, f"✅ **Script Restarted!** `({active_filename})`", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "❌ No previous file found to restart.")

# Handle Uploaded Requirements.txt
def process_requirements_file(message):
    chat_id = message.chat.id
    if not message.document or not message.document.file_name.endswith('.txt'):
        bot.send_message(chat_id, "❌ **Error:** Please upload a valid `requirements.txt` file.")
        return

    msg = bot.send_message(chat_id, "📥 **Downloading and installing requirements.txt...**")
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with open("uploaded_req.txt", 'wb') as f:
            f.write(downloaded_file)

        subprocess.check_call(['python', '-m', 'pip', 'install', '-r', 'uploaded_req.txt'])
        bot.edit_message_text("✅ **All requirements installed successfully!** Now you can upload your `.py` file.", chat_id, msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ **Error installing requirements:** `{str(e)}`", chat_id, msg.message_id, parse_mode="Markdown")

# Handle Uploaded Python File
def process_uploaded_file(message):
    chat_id = message.chat.id
    
    if not message.document or not message.document.file_name.endswith('.py'):
        bot.send_message(chat_id, "❌ **Error:** Please send a `.py` file format.")
        return

    progress_msg = bot.send_message(chat_id, "🔄 **Step 1/4: Downloading Script...**\n`[██░░░░░░░░] 20%`", parse_mode="Markdown")
    
    try:
        # Step 1: Download
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        global active_filename, running_process, start_time
        active_filename = message.document.file_name
        with open(active_filename, 'wb') as f:
            f.write(downloaded_file)

        # Step 2: Extract & Install Dependencies Automatically
        bot.edit_message_text("🔍 **Step 2/4: Scanning & Auto-Installing Pip Packages...**\n`[████░░░░░░] 40%`", 
                               chat_id, progress_msg.message_id, parse_mode="Markdown")
        
        needed_modules = extract_requirements(active_filename)
        auto_install_packages(needed_modules, chat_id, progress_msg)

        # Step 3: Terminate previous running script if any
        bot.edit_message_text("⚙️ **Step 3/4: Allocating Background Memory...**\n`[████████░░] 80%`", 
                               chat_id, progress_msg.message_id, parse_mode="Markdown")
        
        if running_process and running_process.poll() is None:
            running_process.terminate()

        # Step 4: Run as Subprocess
        running_process = subprocess.Popen(['python', active_filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        start_time = time.time()

        bot.edit_message_text("✅ **Step 4/4: Execution Complete!**\n`[██████████] 100%`\n\n🟢 **YOUR SCRIPT/BOT IS ONLINE 24/7!**", 
                               chat_id, progress_msg.message_id, parse_mode="Markdown")
        bot.send_message(chat_id, "🎛️ **Use control panel to manage:**", reply_markup=get_control_menu())

    except Exception as e:
        bot.edit_message_text(f"❌ **Execution Failed Error:**\n`{str(e)}`", chat_id, progress_msg.message_id, parse_mode="Markdown")

def run_bot():
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    # Start Telegram Bot in Background
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    
    # Start Flask Web Server for Render Keep-Alive
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
