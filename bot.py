#!/usr/bin/env python3
import os
import time
import random
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

USER_AGENT = "SubredditAnalyzerTelegram/4.0 (by /u/Aggravating_Lock_666)"
BASE = "https://api.reddit.com"

def fetch(url, params=None):
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.2, 1.8))
            r = requests.get(
                f"{BASE}{url}",
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                params=params,
                timeout=15
            )

            print(f"[FETCH] {url} | status={r.status_code}")

            if r.status_code == 429:
                wait_s = 10 * (attempt + 1)
                print(f"[FETCH] rate limited, waiting {wait_s}s")
                time.sleep(wait_s)
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            print(f"[FETCH ERROR] {url} | attempt={attempt+1} | error={e}")

    return None

def analyze(subreddit):
    subreddit = subreddit.replace("https://www.reddit.com/r/", "")
    subreddit = subreddit.replace("https://reddit.com/r/", "")
    subreddit = subreddit.replace("r/", "")
    subreddit = subreddit.strip().strip("/")

    if not subreddit:
        return "Use: /analyze subreddit"

    sub = fetch(f"/r/{subreddit}/about.json")
    if not sub or "data" not in sub:
        return f"❌ Could not fetch r/{subreddit}"

    data = sub["data"]
    subscribers = data.get("subscribers", "N/A")
    title = data.get("title", "N/A")
    public_description = data.get("public_description", "N/A")
    over18 = data.get("over18", False)

    lines = []
    lines.append(f"📊 r/{subreddit}")
    lines.append(f"📝 Title: {title}")
    lines.append(f"👥 Subscribers: {subscribers}")
    lines.append(f"🔞 NSFW: {'Yes' if over18 else 'No'}")
    lines.append(f"📣 Description: {public_description}")

    rules_data = fetch(f"/r/{subreddit}/about/rules.json")
    if rules_data and rules_data.get("rules"):
        lines.append("")
        lines.append("📜 Rules:")
        for i, rule in enumerate(rules_data["rules"][:5], 1):
            rule_name = rule.get("short_name") or rule.get("violation_reason") or "Rule"
            lines.append(f"{i}. {rule_name}")

    return "\n".join(lines)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi 👋\nUse /analyze subreddit\nExamples:\n/analyze tressless\n/analyze AskReddit"
    )

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: /analyze subreddit")
        return

    subreddit = context.args[0]
    await update.message.reply_text(f"Working on r/{subreddit.replace('r/', '').strip('/')}...")

    result = analyze(subreddit)
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
