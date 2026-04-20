#!/usr/bin/env python3
import os
import time
import random
import html
import requests
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

USER_AGENT = "SubredditAnalyzerTelegram/9.0 (by /u/Aggravating_Lock_666)"
API_BASE = "https://api.reddit.com"
WEB_BASE = "https://www.reddit.com"
SAMPLE_LIMIT = 12
MIN_POST_AGE_HOURS = 3

# Leer = jeder darf den Bot nutzen
ALLOWED_USERS = []

def _do_get(base, url, params=None):
    r = requests.get(
        f"{base}{url}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        },
        params=params,
        timeout=15
    )
    print(f"[FETCH] {base}{url} | status={r.status_code}")
    r.raise_for_status()
    return r.json()

def fetch(url, params=None):
    for attempt in range(3):
        try:
            time.sleep(random.uniform(0.4, 0.8))
            try:
                return _do_get(API_BASE, url, params=params)
            except Exception as e_api:
                print(f"[FETCH API ERROR] {url} | {e_api}")
                time.sleep(0.2)
                return _do_get(WEB_BASE, url, params=params)
        except Exception as e:
            print(f"[FETCH ERROR] {url} | attempt={attempt+1} | error={e}")
            if "429" in str(e):
                wait_s = 5 * (attempt + 1)
                time.sleep(wait_s)
    return None

def get_subreddit_info(subreddit):
    try:
        data = _do_get(API_BASE, f"/r/{subreddit}/about.json")
        if data and "data" in data:
            return data
    except Exception as e:
        print(f"[SUB INFO API ERROR] {subreddit} | {e}")

    try:
        data = _do_get(WEB_BASE, f"/r/{subreddit}/about.json")
        if data and "data" in data:
            return data
    except Exception as e:
        print(f"[SUB INFO WEB ERROR] {subreddit} | {e}")

    return None

def clean_subreddit_name(subreddit):
    subreddit = subreddit.strip()

    if subreddit.startswith("r/"):
        return subreddit[2:]

    if "/r/" in subreddit:
        return subreddit.split("/r/")[-1].strip("/")

    return subreddit.strip("/")

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

def get_subreddit_rules(subreddit, max_rules=10):
    data = fetch(f"/r/{subreddit}/about/rules.json")
    if not data:
        return []

    rules = data.get("rules", []) or []
    cleaned = []

    for rule in rules[:max_rules]:
        rule_text = (
            rule.get("short_name")
            or rule.get("description")
            or rule.get("violation_reason")
        )
        if rule_text:
            cleaned.append(rule_text.strip())

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
        removed_by_category = d.get("removed_by_category")
        selftext = d.get("selftext", "")
        title = d.get("title", "")
        is_self = d.get("is_self", False)

        if not created or not author or author == "[deleted]":
            continue

        if (now_ts - created) < min_age_seconds:
            continue

        # Sichtbar / nicht moderiert entfernt
        if removed_by_category is not None:
            continue

        # Textposts mit [removed] rausfiltern
        if is_self and isinstance(selftext, str) and selftext.strip().lower() == "[removed]":
            continue

        # Sicherheitshalber kaputte Titel raus
        if isinstance(title, str) and title.strip().lower() == "[removed]":
            continue

        candidates.append(d)

    return candidates

def get_activity(subreddit):
    posts = fetch(f"/r/{subreddit}/new.json", {"limit": SAMPLE_LIMIT})
    post_times = []

    if posts and "data" in posts:
        for item in posts["data"].get("children", []):
            d = item.get("data", {})
            created = d.get("created_utc")
            if created:
                post_times.append(created)

    if len(post_times) >= 2:
        hours_span = (max(post_times) - min(post_times)) / 3600
        posts_per_day = (len(post_times) / max(hours_span, 0.1)) * 24
    else:
        posts_per_day = 0

    if posts_per_day > 50:
        activity_level = "VERY ACTIVE"
    elif posts_per_day > 10:
        activity_level = "ACTIVE"
    elif posts_per_day > 2:
        activity_level = "MODERATE"
    elif posts_per_day > 0.5:
        activity_level = "LOW"
    else:
        activity_level = "DEAD"

    return posts_per_day, activity_level

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
    created_utc = d.get("created_utc")

    return {
        "u": username,
        "t": total,
        "p": pk,
        "c": ck,
        "created_utc": created_utc,
        "a": human_age(created_utc),
        "created_date": iso_date(created_utc),
    }

def find_lowest_and_newest_successful_posts(candidate_posts):
    lowest = None
    newest = None
    lowest_total = float("inf")
    newest_created = 0

    for post in candidate_posts:
        username = post.get("author")
        if not username:
            continue

        info = lookup_user(username)
        if not info:
            continue

        result = {
            "u": info["u"],
            "t": info["t"],
            "p": info["p"],
            "c": info["c"],
            "created_utc": info["created_utc"],
            "a": info["a"],
            "created_date": info["created_date"],
            "post_title": post.get("title", "N/A"),
        }

        if info["t"] < lowest_total:
            lowest = result
            lowest_total = info["t"]

        if info["created_utc"] > newest_created:
            newest = result
            newest_created = info["created_utc"]

    return lowest, newest

def build_message(subreddit, subscribers, sub_age, activity_level, posts_per_day, lowest, newest, rules):
    lines = []
    lines.append(f"📊 <b>Analysis for r/{html.escape(subreddit)}</b>")
    lines.append("")
    lines.append("📈 <b>Activity</b>")
    lines.append(f"• Status: {html.escape(activity_level)}")
    lines.append(f"• Subscribers: {html.escape(format_num(subscribers))}")
    lines.append(f"• Age: {html.escape(sub_age)}")
    lines.append(f"• Posts/day: {html.escape(str(round(posts_per_day, 1)))}")
    lines.append("")

    if lowest:
        lines.append("🏆 <b>Lowest successful visible post</b>")
        lines.append(f"• Total karma: {lowest['t']}")
        lines.append(f"• Post karma: {lowest['p']}")
        lines.append(f"• Comment karma: {lowest['c']}")
        lines.append(f"• User: u/{html.escape(lowest['u'])}")
        lines.append(f"• Account age: {html.escape(lowest['a'])} (created on {html.escape(lowest['created_date'])})")
        lines.append(f"• Post: {html.escape(lowest['post_title'])}")
        lines.append("")

    if newest:
        lines.append("🐣 <b>Newest successful visible post</b>")
        lines.append(f"• Total karma: {newest['t']}")
        lines.append(f"• Post karma: {newest['p']}")
        lines.append(f"• Comment karma: {newest['c']}")
        lines.append(f"• User: u/{html.escape(newest['u'])}")
        lines.append(f"• Account age: {html.escape(newest['a'])} (created on {html.escape(newest['created_date'])})")
        lines.append(f"• Post: {html.escape(newest['post_title'])}")
        lines.append("")

    if rules:
        lines.append("📜 <b>Rules</b>")
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {html.escape(rule)}")
        lines.append("")

    lines.append("<i>Observed from visible posts older than 3 hours. These are practical indicators, not guaranteed subreddit limits.</i>")
    return "\n".join(lines)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi 👋\nUse /analyze r/subreddit\nExamples:\n/analyze r/tressless\n/analyze r/AskReddit"
    )

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USERS and update.effective_user.id not in ALLOWED_USERS:
        await update.message.reply_text("You are not allowed to use this bot.")
        return

    if not context.args:
        await update.message.reply_text("Use: /analyze r/subreddit")
        return

    subreddit = clean_subreddit_name(context.args[0])

    if not subreddit:
        await update.message.reply_text("Use: /analyze r/subreddit")
        return

    await update.message.reply_text(f"Working on r/{subreddit}...")

    sub_info = get_subreddit_info(subreddit)
    if not sub_info or "data" not in sub_info:
        await update.message.reply_text(f"Could not fetch r/{subreddit}")
        return

    s = sub_info["data"]
    subscribers = s.get("subscribers", "N/A")
    sub_age = human_age(s.get("created_utc"))

    posts_per_day, activity_level = get_activity(subreddit)
    candidate_posts = get_candidate_posts(subreddit)
    lowest, newest = find_lowest_and_newest_successful_posts(candidate_posts)
    rules = get_subreddit_rules(subreddit, max_rules=10)

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

    await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
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
