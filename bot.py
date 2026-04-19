#!/usr/bin/env python3
import os
import time
import random
import html
import requests
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

USER_AGENT = "SubredditAnalyzerTelegram/5.0 (by /u/Aggravating_Lock_666)"
BASE = "https://api.reddit.com"
SAMPLE_LIMIT = 12
MIN_POST_AGE_HOURS = 3

def fetch(url, params=None):
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.2, 1.8))
            r = requests.get(
                f"{BASE}{url}",
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json"
                },
                params=params,
                timeout=15
            )

            print(f"[FETCH] {url} | status={r.status_code}")

            if r.status_code == 429:
                wait_s = 10 * (attempt + 1)
                print(f"[FETCH] Rate limited, waiting {wait_s}s")
                time.sleep(wait_s)
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            print(f"[FETCH ERROR] {url} | attempt={attempt+1} | error={e}")

    return None

def clean_subreddit_name(subreddit):
    subreddit = subreddit.replace("https://www.reddit.com/r/", "")
    subreddit = subreddit.replace("https://reddit.com/r/", "")
    subreddit = subreddit.replace("r/", "")
    subreddit = subreddit.strip().strip("/")
    return subreddit

def human_age(ts):
    if not ts:
        return "N/A"
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(ts, timezone.utc)
    days = age.days
    return f"{days//365}y {days%365}d" if days >= 365 else f"{days}d"

def iso_date(ts):
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")

def format_num(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return "N/A"

def get_subreddit_rules(subreddit, max_rules=5):
    data = fetch(f"/r/{subreddit}/about/rules.json")
    if not data:
        return []

    rules = data.get("rules", []) or []
    cleaned = []

    for rule in rules[:max_rules]:
        short_name = rule.get("short_name") or rule.get("violation_reason") or rule.get("description")
        if short_name:
            cleaned.append(short_name.strip())

    return cleaned

def get_candidate_posts(subreddit):
    posts = fetch(f"/r/{subreddit}/new.json", {"limit": SAMPLE_LIMIT})
    if not posts or "data" not in posts:
        return []

    now_ts = datetime.now(timezone.utc).timestamp()
    min_age_seconds = MIN_POST_AGE_HOURS * 3600

    candidates = []
    for item in posts["data"].get("children", []):
        d = item.get("data", {})
        created = d.get("created_utc")
        author = d.get("author")
        if not created or not author or author == "[deleted]":
            continue
        if (now_ts - created) < min_age_seconds:
            continue
        candidates.append(d)

    return candidates

def get_authors_and_activity(subreddit):
    posts = fetch(f"/r/{subreddit}/new.json", {"limit": SAMPLE_LIMIT})
    comments = fetch(f"/r/{subreddit}/comments.json", {"limit": SAMPLE_LIMIT})

    authors = set()
    post_times = []

    if posts and "data" in posts:
        for item in posts["data"].get("children", []):
            d = item.get("data", {})
            author = d.get("author")
            created = d.get("created_utc")
            if author and author != "[deleted]":
                authors.add(author)
            if created:
                post_times.append(created)

    if comments and "data" in comments:
        for item in comments["data"].get("children", []):
            d = item.get("data", {})
            author = d.get("author")
            if author and author != "[deleted]":
                authors.add(author)

    if len(post_times) >= 2:
        hours_span = (max(post_times) - min(post_times)) / 3600
        posts_per_day = (len(post_times) / max(hours_span, 0.1)) * 24
    else:
        posts_per_day = 0

    if posts_per_day > 50:
        activity_level = "🔥 VERY ACTIVE"
    elif posts_per_day > 10:
        activity_level = "⚡ ACTIVE"
    elif posts_per_day > 2:
        activity_level = "🟡 MODERATE"
    elif posts_per_day > 0.5:
        activity_level = "💤 LOW"
    else:
        activity_level = "⚰️ DEAD"

    return authors, posts_per_day, activity_level

def lookup_user(username):
    user = fetch(f"/user/{username}/about.json")
    if not user or "data" not in user:
        return None

    d = user["data"]
    if d.get("is_suspended") or d.get("is_employee") or not d.get("created_utc"):
        return None

    pk = d.get("link_karma", 0)
    ck = d.get("comment_karma", 0)
    total = pk + ck
    created_utc = d["created_utc"]

    return {
        "u": username,
        "t": total,
        "p": pk,
        "c": ck,
        "created_utc": created_utc,
        "a": human_age(created_utc),
        "created_date": iso_date(created_utc),
        "profile_url": f"https://www.reddit.com/user/{username}"
    }

def pick_lowest_and_newest(authors):
    lowest = None
    newest = None
    lowest_val = float("inf")
    newest_time = 0

    for username in authors:
        info = lookup_user(username)
        if not info:
            continue

        if info["t"] < lowest_val:
            lowest = info
            lowest_val = info["t"]

        if info["created_utc"] > newest_time:
            newest = info
            newest_time = info["created_utc"]

    return lowest, newest

def attach_example_post(user_info, candidate_posts):
    if not user_info:
        return

    username = user_info["u"]
    for post in candidate_posts:
        if post.get("author") == username:
            user_info["post_title"] = post.get("title", "N/A")
            permalink = post.get("permalink")
            user_info["post_url"] = f"https://www.reddit.com{permalink}" if permalink else None
            return

def build_message(subreddit, subscribers, sub_age, activity_level, posts_per_day, lowest, newest, rules):
    lines = []
    lines.append(f"📊 <b>Analysis for r/{html.escape(subreddit)}</b>")
    lines.append("")
    lines.append(f"📈 <b>Activity Status:</b> {html.escape(activity_level)}")
    lines.append(f"👥 <b>Subscribers:</b> {html.escape(format_num(subscribers))}")
    lines.append(f"📅 <b>Subreddit age:</b> {html.escape(sub_age)}")
    lines.append(f"📊 <b>Activity:</b> {html.escape(str(round(posts_per_day, 1)))} posts/day")
    lines.append("")

    if lowest:
        lines.append("🏆 <b>Lowest Karma Account:</b>")
        lines.append(f"💯 <b>Total karma:</b> {lowest['t']}")
        lines.append(f"⬆️ <b>Post karma:</b> {lowest['p']}")
        lines.append(f"💬 <b>Comment karma:</b> {lowest['c']}")
        lines.append(f"👤 <b>User:</b> u/{html.escape(lowest['u'])}")
        lines.append(f"🗓️ <b>Account age:</b> {html.escape(lowest['a'])} (created on {html.escape(lowest['created_date'])})")
        if lowest.get("post_title"):
            lines.append(f"📝 <b>Post:</b> {html.escape(lowest['post_title'])}")
        lines.append("")

    if newest:
        lines.append("🐣 <b>Newest Account:</b>")
        lines.append(f"💯 <b>Total karma:</b> {newest['t']}")
        lines.append(f"⬆️ <b>Post karma:</b> {newest['p']}")
        lines.append(f"💬 <b>Comment karma:</b> {newest['c']}")
        lines.append(f"👤 <b>User:</b> u/{html.escape(newest['u'])}")
        lines.append(f"🗓️ <b>Account age:</b> {html.escape(newest['a'])} (created on {html.escape(newest['created_date'])})")
        if newest.get("post_title"):
            lines.append(f"📝 <b>Post:</b> {html.escape(newest['post_title'])}")
        lines.append("")

    if rules:
        lines.append("📜 <b>Subreddit Rules:</b>")
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {html.escape(rule)}")
        lines.append("")

    lines.append(f"<i>Based on posts older than {MIN_POST_AGE_HOURS} hours.</i>")
    return "\n".join(lines)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi 👋\nUse /analyze subreddit\nExamples:\n/analyze tressless\n/analyze AskReddit"
    )

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: /analyze subreddit")
        return

    subreddit = clean_subreddit_name(context.args[0])

    if not subreddit:
        await update.message.reply_text("Use: /analyze subreddit")
        return

    await update.message.reply_text(f"Working on r/{subreddit}...")

    sub_info = fetch(f"/r/{subreddit}/about.json")
    if not sub_info or "data" not in sub_info:
        await update.message.reply_text(f"Could not fetch r/{subreddit}")
        return

    s = sub_info["data"]
    subscribers = s.get("subscribers", "N/A")
    sub_age = human_age(s.get("created_utc"))

    authors, posts_per_day, activity_level = get_authors_and_activity(subreddit)
    candidate_posts = get_candidate_posts(subreddit)
    lowest, newest = pick_lowest_and_newest(authors)

    attach_example_post(lowest, candidate_posts)
    attach_example_post(newest, candidate_posts)

    rules = get_subreddit_rules(subreddit, max_rules=5)

    message = build_message(
        subreddit=subreddit,
        subscribers=subscribers,
        sub_age=sub_age,
        activity_level=activity_level,
        posts_per_day=posts_per_day,
        lowest=lowest,
        newest=newest,
        rules=rules
    )

    buttons = []
    if lowest and lowest.get("profile_url"):
        buttons.append([InlineKeyboardButton(f"👤 View u/{lowest['u']}'s profile", url=lowest["profile_url"])])
    if newest and newest.get("profile_url"):
        buttons.append([InlineKeyboardButton(f"👤 View u/{newest['u']}'s profile", url=newest["profile_url"])])
    if rules:
        buttons.append([InlineKeyboardButton(f"📜 Open r/{subreddit} rules", url=f"https://www.reddit.com/r/{subreddit}/about/rules")])

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.run_polling()

if __name__ == "__main__":
    main()
