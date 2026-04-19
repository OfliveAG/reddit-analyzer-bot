#!/usr/bin/env python3
import os
import time
import random
import html
import requests
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

USER_AGENT = "SubredditAnalyzerTelegram/3.0 (by /u/Aggravating_Lock_666)"
BASE = "https://www.reddit.com"
SAMPLE_LIMIT = 10

def fetch(url, params=None):
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.6, 2.1))
            r = requests.get(
                f"{BASE}{url}",
                headers={"User-Agent": USER_AGENT},
                params=params,
                timeout=15
            )

            print(f"[FETCH] {url} | status={r.status_code}")

            if r.status_code == 429:
                wait_s = 20 * (attempt + 1)
                time.sleep(wait_s)
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            print(f"[FETCH ERROR] {url} | {e}")

    return None

def human_age(ts):
    if not ts:
        return "N/A"
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(ts, timezone.utc)
    return f"{age.days}d"

def analyze(subreddit):
    sub = fetch(f"/r/{subreddit}/about.json")
    if not sub:
        return f"❌ Could not fetch r/{subreddit}"

    subs = sub["data"].get("subscribers", "N/A")

    return f"📊 r/{subreddit}\n👥 Subscribers: {subs}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /analyze subreddit")

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: /analyze subreddit")
        return

    sub = context.args[0]
    result = analyze(sub)
    await update.message.reply_text(result)

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze_cmd))

    app.run_polling()

if __name__ == "__main__":
    main()
