#!/usr/bin/env python3
import requests, time, random, sys
from datetime import datetime, timezone
USER_AGENT = "SubredditAnalyzer/1.0 (by /u/Aggravating_Lock_666)"
BASE = "https://www.reddit.com"
SAMPLE_LIMIT = 10
def fetch(url, params=None):
    for attempt in range(3):
        try:
            time.sleep(random.uniform(1.8, 2.2))
            r = requests.get(f"{BASE}{url}", headers={"User-Agent": USER_AGENT}, params=params, timeout=15)
            if r.status_code == 429:
                print("Rate limited. Waiting 75s.")
                time.sleep(75)
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            return None
    return None
def human_age(ts):
    if not ts: return "N/A"
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(ts, timezone.utc)
    days = age.days
    return f"{days//365}y {days%365}d" if days >= 365 else f"{days}d"
def analyze(subreddit):
    print(f"Analyzing r/{subreddit}...\n")
    sub_info = fetch(f"/r/{subreddit}/about.json")
    if not sub_info or "data" not in sub_info:
        print("Could not fetch subreddit")
        return
    s = sub_info["data"]
    print(f"r/{subreddit}")
    print(f"Subscribers: {s.get('subscribers', 'N/A')}")
    print(f"Age: {human_age(s.get('created_utc'))}")
    posts = fetch(f"/r/{subreddit}/new.json", {"limit": SAMPLE_LIMIT})
    comments = fetch(f"/r/{subreddit}/comments.json", {"limit": SAMPLE_LIMIT})
    post_times = []
    if posts and "data" in posts:
        for p in posts["data"].get("children", []):
            if p["data"].get("author") != "[deleted]":
                post_times.append(p["data"]["created_utc"])
    if len(post_times) >= 2:
        hours_span = (max(post_times) - min(post_times)) / 3600
        posts_per_day = (len(post_times) / max(hours_span, 0.1)) * 24
    else:
        posts_per_day = 0
    if posts_per_day > 50: activity_level = "VERY ACTIVE"
    elif posts_per_day > 10: activity_level = "ACTIVE"
    elif posts_per_day > 2: activity_level = "MODERATE"
    elif posts_per_day > 0.5: activity_level = "LOW"
    else: activity_level = "DEAD"
    print(f"Activity: {activity_level}")
    authors = set()
    if posts and "data" in posts:
        for item in posts["data"].get("children", []):
            author = item["data"].get("author")
            if author and author != "[deleted]": authors.add(author)
    if comments and "data" in comments:
        for item in comments["data"].get("children", []):
            author = item["data"].get("author")
            if author and author != "[deleted]": authors.add(author)
    print(f"Found {len(authors)} unique authors\n")
    lowest = newest = None
    lowest_val, newest_time = float("inf"), 0
    for i, username in enumerate(authors, 1):
        if i % 20 == 0: print(f"Processing {i}/{len(authors)}...")
        user = fetch(f"/user/{username}/about.json")
        if not user or "data" not in user: continue
        d = user["data"]
        if d.get("is_suspended") or d.get("is_employee") or not d.get("created_utc"): continue
        pk, ck = d.get("link_karma", 0), d.get("comment_karma", 0)
        total, created_utc = pk + ck, d["created_utc"]
        if total < lowest_val: lowest = {"u": username, "t": total, "p": pk, "c": ck, "a": human_age(created_utc)}; lowest_val = total
        if created_utc > newest_time: newest = {"u": username, "t": total, "p": pk, "c": ck, "a": human_age(created_utc)}; newest_time = created_utc
    print("="*60)
    if lowest: print(f"LOWEST KARMA: u/{lowest['u']}\nTotal: {lowest['t']} | Post: {lowest['p']} | Comment: {lowest['c']}\nAge: {lowest['a']}")
    if newest: print(f"NEWEST: u/{newest['u']}\nTotal: {newest['t']} | Post: {newest['p']} | Comment: {newest['c']}\nAge: {newest['a']}")
    print("="*60)
if __name__ == "__main__":
    if len(sys.argv) > 1: analyze(sys.argv[1])
    else:
        sub = input("Enter subreddit (without r/): ").strip()
        if sub: analyze(sub)
