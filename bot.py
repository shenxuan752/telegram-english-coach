import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, JobQueue
import os
from dotenv import load_dotenv
from datetime import time, datetime
import pytz
from threading import Thread
from flask import Flask
import random

from services.gemini_ai import lookup_word, generate_word_of_day, analyze_audio_file, generate_journal_prompt, generate_weekly_mission
from services.database import save_flashcard, get_flashcards, save_journal, save_mission_completion, get_random_journal
from services.tts import text_to_speech
from services.shadowing import generate_shadowing_task, create_reference_audio, analyze_voice_attempt

load_dotenv()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# State management
user_shadowing_tasks = {}
user_journal_states = {} # chat_id -> prompt_text
user_review_states = {} # chat_id -> {words: [], index: 0}

# Flask app for Render keep-alive
app = Flask('')

@app.route('/')
def home():
    return "I am alive! 🤖"

def run_http():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message and set up schedules."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # 1. Word of the Day (9 AM)
    context.job_queue.run_daily(
        send_word_of_day,
        time=time(hour=9, minute=0, tzinfo=pytz.timezone('America/New_York')),
        chat_id=chat_id,
        name=f'wod_{user_id}'
    )
    
    # 2. Weekly Mission (Monday 9 AM)
    context.job_queue.run_daily(
        send_weekly_mission,
        time=time(hour=9, minute=0, tzinfo=pytz.timezone('America/New_York')),
        days=(1,), # Monday
        chat_id=chat_id,
        name=f'mission_{user_id}'
    )
    
    # 3. Daily Journal (9 PM)
    context.job_queue.run_daily(
        send_journal_prompt,
        time=time(hour=21, minute=0, tzinfo=pytz.timezone('America/New_York')),
        chat_id=chat_id,
        name=f'journal_{user_id}'
    )
    
    # 4. Shadowing (10 PM)
    context.job_queue.run_daily(
        send_shadowing_task,
        time=time(hour=22, minute=0, tzinfo=pytz.timezone('America/New_York')),
        chat_id=chat_id,
        name=f'shadowing_{user_id}'
    )
    
    welcome_msg = """👋 **Welcome to English Coach Bot!**

I'm your 24/7 AI Coach powered by Gemini 1.5 Flash (Fast!).

**Daily Schedule:**
☀️ 09:00 AM - Word of the Day
🚀 Mon 9 AM - Weekly Mission
✍️ 09:00 PM - Micro-Journal
🎤 10:00 PM - Shadowing Practice

**Features:**
🔍 **Lookup:** Send ANY word
🎤 **Voice:** Send audio for analysis
🧠 **Review:** /review your words
📊 **Stats:** /stats

**Manual Triggers:**
/wod - Get Word of the Day now
/journal - Get Journal prompt now
/shadowing - Get Shadowing task now
/memory - See a random past journal

Let's start! Send me a word to define."""
    
    await update.message.reply_text(welcome_msg)

# --- Feature 1: Word of the Day ---
async def send_word_of_day(context: ContextTypes.DEFAULT_TYPE):
    try:
        # Handle both Job context and Update context (for manual trigger)
        if isinstance(context, ContextTypes.DEFAULT_TYPE) and context.job:
            chat_id = context.job.chat_id
            bot = context.bot
        else:
            # Manual trigger via command
            # We need to find where to send it. 
            # Actually, for manual commands, we should pass 'update' and reply to it.
            # But to reuse this function, let's assume context.job is set OR we pass chat_id explicitly?
            # Let's refactor slightly.
            pass 
            
    except Exception as e:
        logger.error(f"WOD error: {e}")

# Refactored Sender Functions
async def send_wod_logic(bot, chat_id):
    result = await generate_word_of_day()
    response = f"""☀️ **Word of the Day**

**{result['word'].upper()}**

**Definition:** {result['definition']}
**Chinese:** {result['chinese']}
**Example:** _{result['example']}_"""
    
    await bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
    
    audio_path = await text_to_speech(result['word'])
    with open(audio_path, 'rb') as audio:
        await bot.send_voice(chat_id=chat_id, voice=audio)
    os.remove(audio_path)
    
    await save_flashcard(result, chat_id)

async def send_word_of_day(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job wrapper."""
    await send_wod_logic(context.bot, context.job.chat_id)

async def wod_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual command wrapper."""
    await send_wod_logic(context.bot, update.effective_chat.id)


# --- Feature 2: Weekly Mission ---
async def send_mission_logic(bot, chat_id):
    mission = await generate_weekly_mission()
    msg = f"""🚀 **Weekly Mission: {mission['title']}**

**Task:** {mission['task']}

**💡 Tip:** {mission['tip']}

*Reply with "Mission Complete" when done!*"""
    await bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def send_weekly_mission(context: ContextTypes.DEFAULT_TYPE):
    await send_mission_logic(context.bot, context.job.chat_id)

# --- Feature 3: Micro-Journal ---
async def send_journal_logic(bot, chat_id):
    """Send fixed daily journal questions."""
    prompt = """✍️ **Daily Reflection**

Please answer these 3 questions:

1️⃣ **3 things you feel gratitude for and did well today**
2️⃣ **3 things you think you can improve**  
3️⃣ **3 things you plan to do tomorrow**

*Reply with your answers to save your journal entry!*"""
    
    user_journal_states[chat_id] = "daily_reflection"
    await bot.send_message(chat_id=chat_id, text=prompt, parse_mode='Markdown')

async def send_journal_prompt(context: ContextTypes.DEFAULT_TYPE):
    await send_journal_logic(context.bot, context.job.chat_id)

async def journal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_journal_logic(context.bot, update.effective_chat.id)

# --- Feature 4: Shadowing ---
async def send_shadowing_logic(bot, chat_id):
    task = await generate_shadowing_task()
    user_shadowing_tasks[chat_id] = task
    msg = f"""🎤 **Daily Shadowing**

📰 **Context:** {task['context']}
**Say this:** _{task['sentences']}_"""
    await bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
    
    audio_path = await create_reference_audio(task['sentences'])
    with open(audio_path, 'rb') as audio:
        await bot.send_voice(chat_id=chat_id, voice=audio)
    os.remove(audio_path)

async def send_shadowing_task(context: ContextTypes.DEFAULT_TYPE):
    await send_shadowing_logic(context.bot, context.job.chat_id)

async def shadowing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_shadowing_logic(context.bot, update.effective_chat.id)


# --- Feature 5: Flashcard Review ---
async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a flashcard review session."""
    user_id = update.effective_user.id
    cards = await get_flashcards(user_id, limit=50)
    
    if not cards:
        await update.message.reply_text("No flashcards yet! Lookup some words first.")
        return
        
    # Shuffle and pick 5
    random.shuffle(cards)
    session_cards = cards[:5]
    
    user_review_states[update.effective_chat.id] = {
        'cards': session_cards,
        'index': 0
    }
    
    await send_review_card(update.effective_chat.id, context)

async def send_review_card(chat_id, context):
    state = user_review_states.get(chat_id)
    if not state or state['index'] >= len(state['cards']):
        await context.bot.send_message(chat_id=chat_id, text="🎉 Review complete!")
        if chat_id in user_review_states:
            del user_review_states[chat_id]
        return

    card = state['cards'][state['index']]
    
    keyboard = [[InlineKeyboardButton("👁️ Reveal", callback_data="reveal")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🧠 **Review ({state['index']+1}/{len(state['cards'])})**\n\nWord: **{card['word']}**\n\n*Think of the meaning...*",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    state = user_review_states.get(chat_id)
    
    if not state:
        await query.edit_message_text("Session expired.")
        return

    if query.data == "reveal":
        card = state['cards'][state['index']]
        keyboard = [[InlineKeyboardButton("➡️ Next", callback_data="next")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=f"🧠 **{card['word']}**\n\n📖 {card['definition']}\n🇨🇳 {card['chinese']}\n📝 _{card['example']}_",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif query.data == "next":
        state['index'] += 1
        await send_review_card(chat_id, context)

# --- Handlers ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (Journal vs Word Lookup)."""
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Check if waiting for journal
    if chat_id in user_journal_states:
        prompt = user_journal_states[chat_id]
        
        # Save journal with date
        try:
            entry_date = datetime.now().strftime("%Y-%m-%d")
            result = await save_journal({
                "entry_date": entry_date,
                "entry": text
            }, user_id)
            del user_journal_states[chat_id]
            
            logger.info(f"Journal saved for user {user_id}: {result}")
            await update.message.reply_text("✅ Journal entry saved!")
        except Exception as e:
            logger.error(f"Error saving journal: {e}")
            await update.message.reply_text(f"❌ Error saving journal: {e}")
        return

    # Check for Mission Complete
    if text.lower().startswith("mission complete"):
        await save_mission_completion({'status': 'completed'}, user_id)
        await update.message.reply_text("🎉 Mission accomplished! Great job!")
        return

    # Otherwise: Word Lookup
    if len(text.split()) <= 3:
        await process_word_lookup(update, text)
    else:
        await update.message.reply_text("Just send a word to lookup, or use /help.")

async def process_word_lookup(update: Update, word: str):
    await update.message.reply_text(f"🔍 Looking up '{word}'...")
    try:
        result = await lookup_word(word)
        
        response = f"""📚 **{result['word'].upper()}**

**Definition:** {result['definition']}
**Chinese:** {result['chinese']}
**Example:** _{result['example']}_"""
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
        audio_path = await text_to_speech(result['word'])
        with open(audio_path, 'rb') as audio:
            await update.message.reply_voice(audio)
        os.remove(audio_path)
        
        # Save
        save_result = await save_flashcard(result, update.effective_user.id)
        if save_result and save_result.get('status') == 'skipped':
             await update.message.reply_text("⚠️ Word already in flashcards!")
        else:
             await update.message.reply_text("✅ Saved!")
             
    except Exception as e:
        logger.error(f"Lookup error: {e}")
        await update.message.reply_text("Could not find that word.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    voice_file = await update.message.voice.get_file()
    file_path = f"voice_{chat_id}.ogg"
    await voice_file.download_to_drive(file_path)
    
    await update.message.reply_text("🎧 Analyzing...")
    
    try:
        if chat_id in user_shadowing_tasks:
            # Shadowing feedback
            feedback = await analyze_audio_file(file_path)
            # Use None for parse_mode to avoid markdown errors with raw text
            await update.message.reply_text(f"✅ **Shadowing Feedback**\n\n{feedback['text']}", parse_mode=None)
            del user_shadowing_tasks[chat_id]
        else:
            # General analysis
            feedback = await analyze_audio_file(file_path)
            # Use None for parse_mode to avoid markdown errors with raw text
            await update.message.reply_text(f"🎙️ **Voice Analysis**\n\n{feedback['text']}", parse_mode=None)
            
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


async def memory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retrieve a random past journal entry."""
    user_id = update.effective_user.id
    entry = await get_random_journal(user_id)
    
    if not entry:
        await update.message.reply_text("📝 No journal entries yet! Use /journal to start writing.")
        return
    
    entry_date = entry.get('entry_date', 'Unknown date')
    entry_text = entry.get('entry', 'No content')
    
    msg = f"""📖 **Memory from {entry_date}**

{entry_text}

*Use /memory to see another random entry!*"""
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "**Commands:**\n/shadowing - Practice\n/wod - Word of Day\n/journal - Journal\n/memory - Random journal\n/review - Flashcards\n/stats - Progress\n/help - Info",
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cards = await get_flashcards(user_id, limit=5)
    await update.message.reply_text(f"📊 You have **{len(cards) if cards else 0}** flashcards saved.", parse_mode='Markdown')

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    # Keep-alive server
    t = Thread(target=run_http)
    t.start()
    
    application = Application.builder().token(token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("shadowing", shadowing_command))
    application.add_handler(CommandHandler("wod", wod_command))
    application.add_handler(CommandHandler("journal", journal_command))
    application.add_handler(CommandHandler("review", review_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("memory", memory_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🤖 Bot running...")
    application.run_polling()

if __name__ == '__main__':
    main()
