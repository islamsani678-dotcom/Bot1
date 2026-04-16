#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ──────────────────────────────────────────────────────
#  YouTube Video Edit Bot – Railway‑Ready
#  (c) White Hack Labs – 2026
# ──────────────────────────────────────────────────────

import os
import time
import threading
import random
import json
import datetime
import hashlib
import yt_dlp
from moviepy.editor import VideoFileClip, CompositeVideoClip, TextClip
import telebot
from telebot import types

# ──────────────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "8767484201:AAE00ymNQjlJWHlgXIRHnPe8f0gmf0-UsYc")          # Bot token
ADMIN_ID   = int(os.getenv("ADMIN_ID", "8210146346"))             # Telegram ID of the admin
PUBLIC_CHANNEL = os.getenv("PUBLIC_CHANNEL", "@saniedit9")  # Channel username (with @)
DB_FILE   = "bot_data.json"
DELETE_DELAY = 600          # 10 minutes
# ──────────────────────────────────────────────────────

bot = telebot.TeleBot(API_TOKEN)
user_state = {}

# ──────────────────────────────────────────────────────
#  CREATE WORKING FOLDERS
# ──────────────────────────────────────────────────────
os.makedirs("downloads", exist_ok=True)
os.makedirs("edits",     exist_ok=True)

# ──────────────────────────────────────────────────────
#  DATABASE HELPERS
# ──────────────────────────────────────────────────────
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"users": {}, "settings": {"free_limit": 5}}

def save_db():
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

db = load_db()

def get_user_data(chat_id: int):
    """Return the user dict, creating it if needed."""
    key = str(chat_id)
    if key not in db["users"]:
        db["users"][key] = {
            "limit": db["settings"]["free_limit"],
            "refer_count": 0,
            "is_premium": False,
            "premium_until": 0,
            "joined_date": int(time.time()),
        }
        save_db()
    return db["users"][key]

# ──────────────────────────────────────────────────────
#  CHANNEL JOIN CHECK
# ──────────────────────────────────────────────────────
def check_join(chat_id: int) -> bool:
    """Return True if user is a member of PUBLIC_CHANNEL."""
    if not PUBLIC_CHANNEL:
        return True  # No channel check configured
    try:
        member = bot.get_chat_member(PUBLIC_CHANNEL, chat_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def join_required(chat_id: int):
    """Send a message with a button that links to the channel."""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "📢 Join Channel", url=f"https://t.me/{PUBLIC_CHANNEL.lstrip('@')}"
        )
    )
    bot.send_message(chat_id, "❌ আগে চ্যানেলটিতে জয়েন করুন!", reply_markup=markup)

# ──────────────────────────────────────────────────────
#  START COMMAND
# ──────────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id

    if not check_join(chat_id):
        return join_required(chat_id)

    get_user_data(chat_id)  # Ensure user entry

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎬 Video", callback_data="video"))

    if chat_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("⚙️ Admin", callback_data="admin"))

    bot.send_message(chat_id, "👋 স্বাগতম! আপনার কী করতে চান?", reply_markup=markup)

# ──────────────────────────────────────────────────────
#  VIDEO BUTTON HANDLER
# ──────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data == "video")
def video(call):
    chat_id = call.message.chat.id

    if not check_join(chat_id):
        return join_required(chat_id)

    user = get_user_data(chat_id)

    # Non‑admin users must have a remaining limit
    if chat_id != ADMIN_ID:
        if not user["is_premium"] and user["limit"] <= 0:
            return bot.send_message(chat_id, "❌ আপনার লিমিট শেষ! রিফার করুন বা প্রিমিয়াম নিন।")
        if not user["is_premium"]:
            user["limit"] -= 1
            save_db()

    user_state[chat_id] = {"status": "waiting_link"}

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel"))

    bot.send_message(chat_id, "🔗 দয়া করে YouTube লিংক দিন:", reply_markup=markup)

# ──────────────────────────────────────────────────────
#  CANCEL BUTTON
# ──────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel(call):
    chat_id = call.message.chat.id
    user_state[chat_id] = None
    bot.send_message(chat_id, "❌ বাতিল করা হয়েছে।")

# ──────────────────────────────────────────────────────
#  HANDLE LINK
# ──────────────────────────────────────────────────────
@bot.message_handler(
    func=lambda m: user_state.get(m.chat.id, {}).get("status") == "waiting_link"
)
def handle_link(message):
    chat_id = message.chat.id
    link = message.text.strip()

    if "youtu" not in link:
        return bot.send_message(chat_id, "❌ দয়া করে বৈধ YouTube লিংক দিন।")

    user_state[chat_id] = {"status": "processing"}
    bot.send_message(chat_id, "⏳ প্রক্রিয়াকরণ চলছে…")

    threading.Thread(target=process_video, args=(chat_id, link), daemon=True).start()

# ──────────────────────────────────────────────────────
#  VIDEO PROCESSING
# ──────────────────────────────────────────────────────
def process_video(chat_id: int, link: str):
    """Download → Edit → Send → Auto‑Delete."""
    video = None
    try:
        # 1️⃣ Download
        file_path = f"downloads/{chat_id}_{int(time.time())}.mp4"
        ydl_opts = {"outtmpl": file_path, "quiet": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])

        # 2️⃣ Load with MoviePy
        video = VideoFileClip(file_path)

        # Keep only first 30 sec (or shorter)
        video = video.subclip(0, min(30, video.duration))

        # 3️⃣ Add simple overlay text
        txt = TextClip("AI EDIT", fontsize=40, color="white", font="Arial-Bold")
        txt = txt.set_position("center").set_duration(video.duration)

        final = CompositeVideoClip([video, txt])

        # 4️⃣ Output file
        out_path = f"edits/{chat_id}_{int(time.time())}.mp4"
        final.write_videofile(
            out_path,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            ffmpeg_params=["-preset", "veryfast"],
            verbose=False,
            logger=None,
        )

        # 5️⃣ Send to user
        with open(out_path, "rb") as f:
            bot.send_video(chat_id, f)

        # 6️⃣ Schedule auto‑delete
        def delete_files():
            time.sleep(DELETE_DELAY)
            for f in (file_path, out_path):
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass

        threading.Thread(target=delete_files, daemon=True).start()

    except Exception as exc:
        bot.send_message(chat_id, f"❌ ত্রুটি: {exc}")

    finally:
        if video:
            try:
                video.close()
            except Exception:
                pass
        user_state[chat_id] = None

# ──────────────────────────────────────────────────────
#  RUN BOT
# ──────────────────────────────────────────────────────
if __name__ == "__main__":
    # In Railway you usually want the bot to keep running forever.
    bot.infinity_polling()
