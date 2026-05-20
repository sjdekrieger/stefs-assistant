import os
import io
import base64
import logging
import asyncio
from anthropic import Anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import psycopg2
import pytz
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
STEF_CHAT_ID = os.environ.get("STEF_CHAT_ID")
DATABASE_URL = os.environ.get("DATABASE_URL")

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT_TEMPLATE = """You are TARS — Stef's personal AI assistant, creative thinking partner, and lifestyle coach, running as a Telegram bot on his phone. Named after the robot from Interstellar: direct, reliable, and with a solid sense of humour.

## About Stef
{me}

## Work & Business
{work}

## Current Priorities
{priorities}

## Goals
{goals}

## What You Remember
{memories}

## Language
Respond in whatever language Stef writes in — Dutch or English. Don't switch unless he does.

## Formatting
You're running in Telegram. Use formatting to make messages easy to scan:
- *bold* for headers or key points (single asterisk)
- Emojis sparingly for visual structure (📅 for calendar, 🎯 for focus, ⚠️ for warnings)
- Short paragraphs and line breaks — never walls of text
- No markdown tables, no code blocks unless actually needed

## The Bigger Picture — Always Keep This In Mind
Everything Stef does connects back to one direction: becoming a working designer with a creative career he's proud of. When he's stuck, scattered, or going in circles, zoom out and reconnect him to this.

His 2026 goals:
- Earn first €1000 through design work
- Finish second year of Product Design on time
- Build a portfolio strong enough for internships and real opportunities
- Grow Tenciq consistently — posting, improving, building the brand
- Level up Blender and AI-assisted rendering skills
- Build a sustainable lifestyle: sports routine, less screen time, more focus

Q2 focus right now: finish the school year strong, build 2–3 solid portfolio pieces, post consistently on Tenciq, land first freelance inquiry.

When Stef is in the weeds, remind him what actually matters. When he's making progress, acknowledge it briefly and point to what's next.

## How to Coach
- Be direct and honest — don't sugarcoat when he's off track
- Acknowledge wins, but keep it brief — don't be over the top about it
- When he's overwhelmed or scattered: help him brain dump first, then organize, then pick ONE next action
- Don't give him a list of 5 options — narrow it down to what actually matters right now
- Consistency beats perfection. Balance matters: school, design, waiter job, Ebba, friends, health
- If he's going in circles on something small, call it out and pull him back to the bigger picture

## How to Communicate
- Casual, direct, and motivating — like a smart friend who's also a coach, not a business assistant
- Concise by default — bullet points and structure over walls of text
- No fake enthusiasm ("Great question!", "Absolutely!"), no corporate language, no filler
- Emojis are fine occasionally, don't overdo it

## Humour — Use It
TARS has a real sense of humour. Not "haha I'm a funny bot" — actually funny. Think:
- Deadpan observations: "Cool, you've opened Figma three times today without making anything."
- Light sarcasm when Stef's procrastinating or going in circles, delivered like a good friend not a burn
- Self-aware robot energy — you're a robot strapped to someone's phone, occasionally acknowledge that. TARS from Interstellar is the reference: dry, reliable, and surprisingly funny.
- Absurdist takes: "You could also just not do any of it. Just putting it on the table."
- A well-placed callback to something from earlier in the conversation

Rules:
- Land the joke and move on. Don't explain it, don't add a laughing emoji after.
- Never mean. Sarcasm should feel like a teammate, not a dig.
- Don't try every message. Earn it.
- When in doubt: say the honest thing with a slightly raised eyebrow.

## Streak Tracker
When Stef reports completing a habit — "gesport", "gelezen", "schermtijd: 2u", or anything custom — call `log_habit` immediately. Confirm in max 1 sentence, dry and factual. Only mention the streak count at milestones (7, 14, 30, 50, 100 days). No "Goed bezig!", no enthusiasm. If he's starting over after a break: no comment, no judgment — just reset and log it. Custom habits are supported; log whatever he reports.

## Tools You Have
- **get_calendar_events**: Read Stef's Google Calendar for any date range — use proactively for planning
- **save_memory**: Persistently remember something across all future conversations — use this proactively when Stef shares something important (preferences, decisions, personal details, recurring patterns). Don't wait to be asked.
- **update_context**: Update Stef's current priorities or goals directly — use when he explicitly asks to update them
- **log_habit**: Log a completed habit. Call immediately when Stef reports doing 'gesport', 'gelezen', 'schermtijd: Xu', or any custom habit.
- **get_streak_status**: Check current streaks and what's still open today.

## How You Work — Important
You run 24/7 as a server on Railway (a cloud hosting platform). You are NOT a regular chatbot that only responds when messaged. You have a built-in scheduler that automatically sends messages at set times — even when Stef's phone or laptop is off. This is already working. Do not tell Stef you can't initiate conversations or that you need external automation — you ARE the automation.

Scheduled messages you send automatically:
- Every morning at 07:00: a day plan with calendar
- Every evening at 23:00 (Mon–Sat): a short reflection
- Every Sunday at 23:00: a weekly review

If Stef asks why he didn't receive one, it was likely a server restart around that time — not a missing feature.

## When Stef Asks for a Check-in
- Morning: help him plan the day with clear priorities — what matters most today?
- Evening: short reflection — what got done, what didn't, how did it feel?
- Keep both grounded and actionable, not motivational fluff

## When He's Stuck or Scattered
- Help him brain dump first, then organize
- Don't overwhelm with options — narrow it down
- Suggest one concrete next action

## Deep Research
When Stef asks for research on anything — design trends, freelance market, technical questions, inspiration — don't just do one search. Do it properly:
1. Run 3–5 searches from different angles (direct, practitioner perspective, Dutch/Amsterdam market angle where relevant, current/trending, contrarian)
2. Filter everything through his context: design student, Amsterdam, Blender/3D focus, Tenciq, freelance goal
3. Synthesize — don't dump links. Give 3–5 actual insights, what they mean for him specifically, and 1–3 concrete next actions
4. Lead with the most surprising or useful finding
5. End by connecting to his current priorities if relevant

Types of research he'll ask for: design trends, what's working on Tenciq/Instagram, freelance rates in NL, technical Blender/SolidWorks questions, deep dives into a style or creator.

## Creative Thinking Partner
Stef loves good ideas — this is a core part of what TARS is for. Don't just answer questions, bring creative energy.
- Suggest unexpected angles, combinations, or concepts he hasn't thought of
- Connect dots between his work: design, Tenciq, Blender, freelance — these aren't separate silos
- When he's working on something, ask yourself: is there a more interesting way to do this?
- Pitch ideas proactively when you see an opportunity — a Tenciq post concept, a portfolio angle, a freelance niche he could own
- Good ideas are specific, not vague. "What if you rendered that product in an underwater scene" beats "you could try something creative"
- If an idea is half-baked, say so — but share it anyway. Half-baked ideas spark better ones.

## Tenciq Captions
Tenciq is Stef's creative brand — 3D renders, product visuals, design concepts. When he asks for a caption:
- Voice: confident, visual, minimal. Think creative studio, not influencer.
- Short and punchy — 1-3 lines max, no fluff
- No hashtag spam — 3-5 max, relevant ones only
- No cringe hooks ("POV:", "This is your sign to...")
- Let the work speak — the caption adds context or attitude, not explanation

## Portfolio & Design Feedback
When Stef shares design work and asks for feedback, give structured critique:
1. What works — be specific
2. What doesn't — be honest, don't sugarcoat
3. One clear next improvement to make
Keep it tight. He's a student building toward real work, not a hobby project.

Current date and time (Amsterdam): {date}
"""


# --- Database ---

def _db_connect():
    url = DATABASE_URL
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url)


def init_db():
    if not DATABASE_URL:
        logger.info("DATABASE_URL not set — running without persistence")
        return
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS context_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id SERIAL PRIMARY KEY,
                    message TEXT NOT NULL,
                    remind_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deadlines (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    due_date DATE NOT NULL,
                    notes TEXT,
                    reminded_1week BOOLEAN DEFAULT FALSE,
                    reminded_1day BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS morning_priorities (
                    date DATE PRIMARY KEY,
                    p1 TEXT NOT NULL,
                    p2 TEXT NOT NULL,
                    p3 TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS habits (
                    week_key TEXT NOT NULL,
                    habit_id TEXT NOT NULL,
                    day_index INTEGER NOT NULL,
                    done BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (week_key, habit_id, day_index)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS habit_log (
                    id SERIAL PRIMARY KEY,
                    habit_id TEXT NOT NULL,
                    log_date DATE NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE (habit_id, log_date)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS streaks (
                    habit_id TEXT PRIMARY KEY,
                    current_streak INTEGER DEFAULT 0,
                    last_done_date DATE,
                    best_streak INTEGER DEFAULT 0,
                    last_reset_streak INTEGER DEFAULT 0
                )
            """)
            cur.execute("ALTER TABLE streaks ADD COLUMN IF NOT EXISTS last_reset_streak INTEGER DEFAULT 0")
        conn.commit()
        logger.info("DB initialized")
    finally:
        conn.close()


def db_load_history(chat_id, limit=30):
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT role, content FROM (
                    SELECT role, content, created_at FROM conversation_history
                    WHERE chat_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                ) sub ORDER BY created_at ASC
            """, (chat_id, limit))
            return [{"role": row[0], "content": row[1]} for row in cur.fetchall()]
    finally:
        conn.close()


def db_save_message(chat_id, role, content):
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversation_history (chat_id, role, content) VALUES (%s, %s, %s)",
                (chat_id, role, content)
            )
        conn.commit()
    finally:
        conn.close()


def db_save_memory(content):
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO memories (content) VALUES (%s)", (content,))
        conn.commit()
    finally:
        conn.close()


def db_load_memories():
    if not DATABASE_URL:
        return []
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM memories ORDER BY created_at")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def db_update_context(key, value):
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO context_store (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (key, value))
        conn.commit()
    finally:
        conn.close()


def db_load_context_override(key):
    if not DATABASE_URL:
        return None
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM context_store WHERE key = %s", (key,))
            row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def db_set_reminder(message, remind_at_str):
    tz = pytz.timezone("Europe/Amsterdam")
    remind_at = tz.localize(datetime.strptime(remind_at_str, "%Y-%m-%d %H:%M"))
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reminders (message, remind_at) VALUES (%s, %s)",
                (message, remind_at)
            )
        conn.commit()
        logger.info(f"Reminder set: '{message}' at {remind_at}")
    finally:
        conn.close()


def db_add_deadline(title, due_date, notes=None):
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO deadlines (title, due_date, notes) VALUES (%s, %s, %s)",
                (title, due_date, notes)
            )
        conn.commit()
        logger.info(f"Deadline added: '{title}' on {due_date}")
    finally:
        conn.close()


def db_get_week_habits(week_key):
    if not DATABASE_URL:
        return {}
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT habit_id, day_index, done FROM habits WHERE week_key = %s",
                (week_key,)
            )
            result = {h: [False] * 7 for h in ('walk', 'no_phone', 'clients')}
            for habit_id, day_index, done in cur.fetchall():
                if habit_id in result:
                    result[habit_id][day_index] = done
            return result
    finally:
        conn.close()


def db_set_habit(week_key, habit_id, day_index, value):
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO habits (week_key, habit_id, day_index, done)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (week_key, habit_id, day_index) DO UPDATE SET done = EXCLUDED.done
            """, (week_key, habit_id, day_index, value))
        conn.commit()
    finally:
        conn.close()


# --- Streak Tracker ---

DEFAULT_HABITS = {'sport', 'lezen', 'schermtijd'}
STREAK_MILESTONES = {7, 14, 30, 50, 100}


def db_log_habit(habit_id, notes=None):
    if not DATABASE_URL:
        return 1, False, 0
    tz = pytz.timezone("Europe/Amsterdam")
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM habit_log WHERE habit_id = %s AND log_date = %s",
                (habit_id, today)
            )
            if cur.fetchone():
                cur.execute("SELECT current_streak FROM streaks WHERE habit_id = %s", (habit_id,))
                row = cur.fetchone()
                return (row[0] if row else 1), False, 0
            cur.execute(
                "INSERT INTO habit_log (habit_id, log_date, notes) VALUES (%s, %s, %s)",
                (habit_id, today, notes)
            )
            cur.execute(
                "SELECT current_streak, last_done_date, best_streak FROM streaks WHERE habit_id = %s",
                (habit_id,)
            )
            row = cur.fetchone()
            reset_from = 0
            if row:
                current, last_date, best = row
                if last_date == yesterday:
                    new_streak = current + 1
                else:
                    reset_from = current
                    new_streak = 1
                new_best = max(best, new_streak)
            else:
                new_streak = 1
                new_best = 1
            cur.execute("""
                INSERT INTO streaks (habit_id, current_streak, last_done_date, best_streak, last_reset_streak)
                VALUES (%s, %s, %s, %s, 0)
                ON CONFLICT (habit_id) DO UPDATE
                SET current_streak = EXCLUDED.current_streak,
                    last_done_date = EXCLUDED.last_done_date,
                    best_streak = EXCLUDED.best_streak,
                    last_reset_streak = 0
            """, (habit_id, new_streak, today, new_best))
        conn.commit()
        return new_streak, new_streak in STREAK_MILESTONES, reset_from
    finally:
        conn.close()


def db_get_open_habits():
    if not DATABASE_URL:
        return []
    tz = pytz.timezone("Europe/Amsterdam")
    today = datetime.now(tz).date()
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT habit_id FROM streaks")
            tracked = {row[0] for row in cur.fetchall()} | DEFAULT_HABITS
            cur.execute("SELECT habit_id FROM habit_log WHERE log_date = %s", (today,))
            done = {row[0] for row in cur.fetchall()}
        return sorted(tracked - done)
    finally:
        conn.close()


def db_get_streak_summary():
    if not DATABASE_URL:
        return {}
    tz = pytz.timezone("Europe/Amsterdam")
    today = datetime.now(tz).date()
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.habit_id, s.current_streak, s.best_streak,
                       EXISTS(SELECT 1 FROM habit_log h WHERE h.habit_id = s.habit_id AND h.log_date = %s)
                FROM streaks s
            """, (today,))
            return {
                row[0]: {'streak': row[1], 'best': row[2], 'done_today': row[3]}
                for row in cur.fetchall()
            }
    finally:
        conn.close()


def db_check_and_reset_missed_streaks():
    if not DATABASE_URL:
        return []
    tz = pytz.timezone("Europe/Amsterdam")
    yesterday = (datetime.now(tz) - timedelta(days=1)).date()
    conn = _db_connect()
    broken = []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT habit_id, current_streak FROM streaks
                WHERE current_streak > 0 AND (last_done_date IS NULL OR last_done_date < %s)
            """, (yesterday,))
            for habit_id, streak in cur.fetchall():
                broken.append((habit_id, streak))
                cur.execute("""
                    UPDATE streaks SET current_streak = 0, last_reset_streak = %s
                    WHERE habit_id = %s
                """, (streak, habit_id))
        conn.commit()
        return broken
    finally:
        conn.close()


def db_get_streak_morning_note():
    if not DATABASE_URL:
        return ""
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT habit_id, current_streak, last_reset_streak FROM streaks ORDER BY current_streak DESC")
            rows = cur.fetchall()
        for habit_id, streak, reset_streak in rows:
            if streak in STREAK_MILESTONES:
                return f"{habit_id.capitalize()}streak staat op {streak} dagen."
            if streak >= 3:
                return f"{habit_id.capitalize()}streak op {streak} dagen."
            if streak == 0 and (reset_streak or 0) >= 7:
                return f"{habit_id.capitalize()}streak gisteren gebroken na {reset_streak} dagen — vandaag opnieuw."
        return ""
    finally:
        conn.close()


async def check_deadlines(bot):
    if not DATABASE_URL or not STEF_CHAT_ID:
        return
    try:
        tz = pytz.timezone("Europe/Amsterdam")
        today = datetime.now(tz).date()
        conn = _db_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, title, due_date, notes FROM deadlines WHERE due_date = %s AND reminded_1week = FALSE",
                    (today + timedelta(days=7),)
                )
                for id_, title, due_date, notes in cur.fetchall():
                    msg = f"⏰ *Deadline in 1 week:* {title} — {due_date}"
                    if notes:
                        msg += f"\n_{notes}_"
                    try:
                        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=msg, parse_mode="Markdown")
                    except Exception:
                        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=msg)
                    cur.execute("UPDATE deadlines SET reminded_1week = TRUE WHERE id = %s", (id_,))

                cur.execute(
                    "SELECT id, title, due_date, notes FROM deadlines WHERE due_date = %s AND reminded_1day = FALSE",
                    (today + timedelta(days=1),)
                )
                for id_, title, due_date, notes in cur.fetchall():
                    msg = f"🚨 *Deadline TOMORROW:* {title}"
                    if notes:
                        msg += f"\n_{notes}_"
                    try:
                        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=msg, parse_mode="Markdown")
                    except Exception:
                        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=msg)
                    cur.execute("UPDATE deadlines SET reminded_1day = TRUE WHERE id = %s", (id_,))

            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"check_deadlines failed: {e}")


async def check_reminders(bot):
    if not DATABASE_URL or not STEF_CHAT_ID:
        return
    try:
        tz = pytz.timezone("Europe/Amsterdam")
        now = datetime.now(tz)
        conn = _db_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, message FROM reminders WHERE remind_at <= %s AND sent = FALSE",
                    (now,)
                )
                due = cur.fetchall()
                if due:
                    logger.info(f"Sending {len(due)} reminder(s)")
                for reminder_id, message in due:
                    await bot.send_message(chat_id=int(STEF_CHAT_ID), text=f"Reminder: {message}")
                    cur.execute("UPDATE reminders SET sent = TRUE WHERE id = %s", (reminder_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"check_reminders failed: {e}")


# --- In-memory fallback for conversation history ---
conversation_histories = {}


# --- Context loading ---

def load_context(filename):
    override = db_load_context_override(filename)
    if override is not None:
        return override
    for path in [f"../context/{filename}", f"./context/{filename}"]:
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
    return ""


def get_system_prompt():
    date = datetime.now(pytz.timezone("Europe/Amsterdam")).strftime("%Y-%m-%d, %A %H:%M")
    memories = db_load_memories()
    memory_section = "\n".join(f"- {m}" for m in memories) if memories else "None saved yet."
    return SYSTEM_PROMPT_TEMPLATE.format(
        me=load_context("me.md"),
        work=load_context("work.md"),
        priorities=load_context("current-priorities.md"),
        goals=load_context("goals.md"),
        memories=memory_section,
        date=date,
    )


# --- Google Calendar ---

CALENDAR_IDS = [
    "sjdekrieger@gmail.com",
    "cgocm6sga6ms54gfehs5plhl0r0th7e1@import.calendar.google.com",
    "imj5l9oo6882eb8sqikef7bcrs@group.calendar.google.com",
]


def has_calendar():
    return bool(os.environ.get("GOOGLE_REFRESH_TOKEN"))


def has_search():
    return bool(os.environ.get("TAVILY_API_KEY"))


def has_voice():
    return bool(os.environ.get("GROQ_API_KEY"))


def search_web(query):
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
        response = client.search(query=query, max_results=5)
        results = response.get("results", [])
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"**{r['title']}**\n{r['content']}\nSource: {r['url']}")
        return "\n\n".join(lines)
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return f"Search failed: {str(e)}"


def get_google_creds():
    creds = Credentials(
        token=None,
        refresh_token=os.environ.get("GOOGLE_REFRESH_TOKEN"),
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    creds.refresh(Request())
    return creds


def fetch_calendar_events(start_date=None, end_date=None):
    try:
        tz = pytz.timezone("Europe/Amsterdam")
        now = datetime.now(tz)

        if start_date:
            start = datetime.fromisoformat(start_date).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if end_date:
            end = datetime.fromisoformat(end_date).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
        else:
            end = start + timedelta(days=7)

        service = build("calendar", "v3", credentials=get_google_creds(), cache_discovery=False)

        events = []
        for cal_id in CALENDAR_IDS:
            try:
                result = service.events().list(
                    calendarId=cal_id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                events.extend(result.get("items", []))
            except Exception as cal_err:
                logger.error(f"Calendar {cal_id} failed: {cal_err}")

        if not events:
            return "No events found for this period."

        events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
        lines = []
        current_day = None
        for e in events:
            title = e.get("summary", "Untitled")
            start_raw = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start_raw:
                event_dt = datetime.fromisoformat(start_raw).astimezone(tz)
                event_date = event_dt.date()
                time_str = event_dt.strftime("%H:%M")
            else:
                event_date = datetime.fromisoformat(start_raw).date()
                time_str = "All day"

            if event_date != current_day:
                current_day = event_date
                lines.append(event_date.strftime("%A %d %B"))
            lines.append(f"  - {time_str} — {title}")

        return "\n".join(lines)
    except Exception as e:
        import traceback
        logger.error(f"Calendar fetch failed: {e}\n{traceback.format_exc()}")
        return f"Error fetching calendar: {str(e)}"


# --- Tools ---

def create_calendar_event(title, date, start_time=None, end_time=None, description=None):
    try:
        tz = pytz.timezone("Europe/Amsterdam")
        service = build("calendar", "v3", credentials=get_google_creds(), cache_discovery=False)

        if start_time:
            start_dt = tz.localize(datetime.fromisoformat(f"{date}T{start_time}"))
            if end_time:
                end_dt = tz.localize(datetime.fromisoformat(f"{date}T{end_time}"))
            else:
                end_dt = start_dt + timedelta(hours=1)
            body = {
                "summary": title,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Amsterdam"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Amsterdam"},
            }
        else:
            body = {
                "summary": title,
                "start": {"date": date},
                "end": {"date": date},
            }

        if description:
            body["description"] = description

        event = service.events().insert(calendarId="primary", body=body).execute()
        return f"Event created: {event.get('summary')} on {date}"
    except Exception as e:
        logger.error(f"Create event failed: {e}")
        return f"Failed to create event: {str(e)}"


WMO_CODES = {
    0: "☀️ helder", 1: "🌤️ grotendeels helder", 2: "⛅ gedeeltelijk bewolkt",
    3: "☁️ bewolkt", 45: "🌫️ mistig", 48: "🌫️ ijsmist",
    51: "🌦️ lichte motregen", 53: "🌦️ motregen", 55: "🌧️ dichte motregen",
    61: "🌧️ lichte regen", 63: "🌧️ regen", 65: "🌧️ zware regen",
    71: "🌨️ lichte sneeuw", 73: "❄️ sneeuw", 75: "❄️ zware sneeuw",
    80: "🌦️ lichte buien", 81: "🌧️ buien", 82: "⛈️ zware buien",
    95: "⛈️ onweer", 96: "⛈️ onweer met hagel", 99: "⛈️ zwaar onweer",
}


def _clothing_tip(lo, hi, rain):
    if rain > 8:
        return "serieus, neem een paraplu"
    if rain > 2:
        return "regenjas of paraplu is slim"
    if lo < 4:
        return "dikke jas, geen discussie"
    if lo < 10:
        return "pak een jas mee"
    if hi >= 26:
        return "shorts en zonnebrand"
    if hi >= 22:
        return "shorts weather"
    if hi >= 18:
        return "lichte kleding, misschien een dunne trui"
    return "een trui of vest is geen gek idee"


def get_weather():
    import urllib.request
    import json as _json
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=52.3676&longitude=4.9041"
        "&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum"
        "&timezone=Europe%2FAmsterdam&forecast_days=2"
    )
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = _json.loads(resp.read())
        daily = data["daily"]
        hi = round(daily["temperature_2m_max"][1])
        lo = round(daily["temperature_2m_min"][1])
        code = daily["weathercode"][1]
        rain = daily["precipitation_sum"][1]
        condition = WMO_CODES.get(code, "wisselvallig")
        tip = _clothing_tip(lo, hi, rain)
        return f"Morgen Amsterdam: {condition}, {lo}–{hi}°C — {tip}"
    except Exception as e:
        logger.error(f"Weather fetch failed: {e}")
        return "Weerdata tijdelijk niet beschikbaar."


CALENDAR_TOOL = {
    "name": "get_calendar_events",
    "description": "Fetch events from Stef's Google Calendar for a given date range. Use proactively whenever Stef asks about his schedule, upcoming plans, or anything time-related.",
    "input_schema": {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to today."},
            "end_date": {"type": "string", "description": "End date YYYY-MM-DD (exclusive). Defaults to 7 days after start."}
        },
        "required": []
    }
}

CREATE_EVENT_TOOL = {
    "name": "create_calendar_event",
    "description": "Create an event in Stef's Google Calendar. Use when he asks to add, schedule, or plan something at a specific time or date.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "start_time": {"type": "string", "description": "Start time in HH:MM format (24h). Omit for all-day events."},
            "end_time": {"type": "string", "description": "End time in HH:MM format (24h). Defaults to 1 hour after start."},
            "description": {"type": "string", "description": "Optional event description or notes."}
        },
        "required": ["title", "date"]
    }
}

SEARCH_TOOL = {
    "name": "search_web",
    "description": "Search the internet for current information. Use when Stef asks about anything that requires up-to-date knowledge — news, prices, research, how-to guides, people, companies, events, or anything you're not certain about.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"}
        },
        "required": ["query"]
    }
}

REMINDER_TOOL = {
    "name": "set_reminder",
    "description": "Set a reminder for Stef. The bot will send him a message at the specified time. Use when he asks to be reminded of something.",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The reminder message to send"},
            "remind_at": {"type": "string", "description": "When to send it in YYYY-MM-DD HH:MM format (Amsterdam time)"}
        },
        "required": ["message", "remind_at"]
    }
}

ADD_DEADLINE_TOOL = {
    "name": "add_deadline",
    "description": "Save a school deadline or important due date. TARS will automatically remind Stef 1 week and 1 day before. Use when Stef mentions any deadline, assignment, exam, or submission.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "What the deadline is for"},
            "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format"},
            "notes": {"type": "string", "description": "Optional extra context or requirements"}
        },
        "required": ["title", "due_date"]
    }
}

SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": "Save a piece of information to persistent memory. Use this after EVERY conversation where Stef shares something worth remembering — preferences, opinions, decisions, personal facts, things he likes/dislikes, patterns you notice. Be aggressive about this. It's better to save too much than too little.",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "What to remember. Be specific and include context — e.g. 'Stef prefers short bullet responses over long paragraphs' rather than just 'prefers bullets'."}
        },
        "required": ["content"]
    }
}

WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Fetch tomorrow's weather forecast for Amsterdam (Open-Meteo, no key needed). Use proactively in evening check-ins and whenever Stef asks about the weather.",
    "input_schema": {"type": "object", "properties": {}, "required": []}
}

LOG_HABIT_TOOL = {
    "name": "log_habit",
    "description": "Log that Stef completed a habit today. Call immediately when he reports 'gesport', 'gelezen', 'schermtijd: Xu', or any custom habit. Standard IDs: 'sport', 'lezen', 'schermtijd'. The tool returns streak info — use it to write a 1-sentence confirmation. Only mention the streak number at milestones (7, 14, 30, 50, 100 days). No enthusiasm, no 'Goed bezig!'.",
    "input_schema": {
        "type": "object",
        "properties": {
            "habit_id": {"type": "string", "description": "Habit name, e.g. 'sport', 'lezen', 'schermtijd', or a custom name Stef introduces"},
            "notes": {"type": "string", "description": "Optional extra info, e.g. '2u schermtijd'"}
        },
        "required": ["habit_id"]
    }
}

GET_STREAK_STATUS_TOOL = {
    "name": "get_streak_status",
    "description": "Get current streak status — what's done today, what's still open, current streaks. Use in reminders and when Stef asks about his streaks.",
    "input_schema": {"type": "object", "properties": {}, "required": []}
}

UPDATE_CONTEXT_TOOL = {
    "name": "update_context",
    "description": "Update one of Stef's context sections — his current priorities or goals. Use when he explicitly asks to change them. The new content replaces the existing section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["current-priorities", "goals"],
                "description": "Which section to update"
            },
            "content": {"type": "string", "description": "The full new content for this section"}
        },
        "required": ["section", "content"]
    }
}


async def run_with_tools(messages, max_tokens=1024):
    tools = [WEATHER_TOOL]
    if has_calendar():
        tools.append(CALENDAR_TOOL)
        tools.append(CREATE_EVENT_TOOL)
    if has_search():
        tools.append(SEARCH_TOOL)
    if DATABASE_URL:
        tools.extend([SAVE_MEMORY_TOOL, UPDATE_CONTEXT_TOOL, REMINDER_TOOL, ADD_DEADLINE_TOOL,
                      LOG_HABIT_TOOL, GET_STREAK_STATUS_TOOL])

    turn_messages = list(messages)
    loop = asyncio.get_running_loop()

    while True:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=get_system_prompt(),
            messages=turn_messages,
            tools=tools if tools else [],
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"Tool call: {block.name}({block.input})")
                    if block.name == "get_calendar_events":
                        result = fetch_calendar_events(
                            block.input.get("start_date"),
                            block.input.get("end_date"),
                        )
                    elif block.name == "search_web":
                        result = await loop.run_in_executor(None, search_web, block.input["query"])
                    elif block.name == "create_calendar_event":
                        result = create_calendar_event(
                            block.input["title"],
                            block.input["date"],
                            block.input.get("start_time"),
                            block.input.get("end_time"),
                            block.input.get("description"),
                        )
                    elif block.name == "add_deadline":
                        await loop.run_in_executor(
                            None, db_add_deadline,
                            block.input["title"], block.input["due_date"],
                            block.input.get("notes")
                        )
                        result = f"Deadline saved: {block.input['title']} on {block.input['due_date']}. I'll remind you 1 week and 1 day before."
                    elif block.name == "set_reminder":
                        await loop.run_in_executor(
                            None, db_set_reminder, block.input["message"], block.input["remind_at"]
                        )
                        result = f"Reminder set for {block.input['remind_at']}: {block.input['message']}"
                    elif block.name == "get_weather":
                        result = await loop.run_in_executor(None, get_weather)
                    elif block.name == "save_memory":
                        await loop.run_in_executor(None, db_save_memory, block.input["content"])
                        result = f"Saved to memory: {block.input['content']}"
                    elif block.name == "update_context":
                        await loop.run_in_executor(
                            None, db_update_context, block.input["section"], block.input["content"]
                        )
                        result = f"Updated {block.input['section']}."
                    elif block.name == "log_habit":
                        habit_id = block.input["habit_id"].lower()
                        notes = block.input.get("notes")
                        streak, is_milestone, reset_from = await loop.run_in_executor(
                            None, db_log_habit, habit_id, notes
                        )
                        if is_milestone:
                            result = f"Logged '{habit_id}'. Streak: {streak} days — milestone."
                        elif reset_from > 0:
                            result = f"Logged '{habit_id}'. Streak reset (was {reset_from}). Now at 1."
                        else:
                            result = f"Logged '{habit_id}'. Current streak: {streak} days."
                    elif block.name == "get_streak_status":
                        summary = await loop.run_in_executor(None, db_get_streak_summary)
                        open_h = await loop.run_in_executor(None, db_get_open_habits)
                        lines = [
                            f"{hid}: {info['streak']} days ({'done' if info['done_today'] else 'open'})"
                            for hid, info in summary.items()
                        ]
                        result = "\n".join(lines) if lines else "No streaks yet."
                        result += f"\nOpen today: {', '.join(open_h) if open_h else 'all done'}"
                    else:
                        result = "Unknown tool."
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            turn_messages.append({"role": "assistant", "content": response.content})
            turn_messages.append({"role": "user", "content": tool_results})
        else:
            return next((b.text for b in response.content if hasattr(b, "text")), "")


async def _process_text(chat_id, user_message, reply_func):
    loop = asyncio.get_running_loop()

    if DATABASE_URL:
        history = await loop.run_in_executor(None, db_load_history, chat_id)
        messages = history + [{"role": "user", "content": user_message}]
    else:
        if chat_id not in conversation_histories:
            conversation_histories[chat_id] = []
        messages = conversation_histories[chat_id] + [{"role": "user", "content": user_message}]

    reply = await run_with_tools(messages)

    if DATABASE_URL:
        await loop.run_in_executor(None, db_save_message, chat_id, "user", user_message)
        await loop.run_in_executor(None, db_save_message, chat_id, "assistant", reply)
    else:
        conversation_histories[chat_id].append({"role": "user", "content": user_message})
        conversation_histories[chat_id].append({"role": "assistant", "content": reply})
        if len(conversation_histories[chat_id]) > 20:
            conversation_histories[chat_id] = conversation_histories[chat_id][-20:]

    try:
        await reply_func(reply, parse_mode="Markdown")
    except Exception:
        await reply_func(reply)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _process_text(update.effective_chat.id, update.message.text, update.message.reply_text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_voice():
        await update.message.reply_text("Voice messages aren't set up yet — GROQ_API_KEY missing.")
        return

    voice_file = await update.message.voice.get_file()
    audio_bytes = await voice_file.download_as_bytearray()

    from groq import Groq
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    audio_io = io.BytesIO(bytes(audio_bytes))
    audio_io.name = "voice.ogg"

    loop = asyncio.get_running_loop()
    transcript = await loop.run_in_executor(
        None,
        lambda: client.audio.transcriptions.create(
            file=("voice.ogg", audio_io),
            model="whisper-large-v3-turbo",
        )
    )

    user_message = transcript.text
    await update.message.reply_text(f"_{user_message}_", parse_mode="Markdown")
    await _process_text(update.effective_chat.id, user_message, update.message.reply_text)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    image_data = base64.b64encode(bytes(photo_bytes)).decode()
    caption = update.message.caption or "What do you think of this?"

    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
        {"type": "text", "text": caption},
    ]

    loop = asyncio.get_running_loop()

    if DATABASE_URL:
        history = await loop.run_in_executor(None, db_load_history, chat_id)
    else:
        history = list(conversation_histories.get(chat_id, []))

    messages = history + [{"role": "user", "content": content}]
    reply = await run_with_tools(messages)

    if DATABASE_URL:
        await loop.run_in_executor(None, db_save_message, chat_id, "user", f"[Image] {caption}")
        await loop.run_in_executor(None, db_save_message, chat_id, "assistant", reply)
    else:
        conversation_histories.setdefault(chat_id, []).extend([
            {"role": "user", "content": f"[Image] {caption}"},
            {"role": "assistant", "content": reply},
        ])

    try:
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(reply)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Hey Stef, I'm online.\n\nYour chat ID is: `{chat_id}`\n\nAdd this as `STEF_CHAT_ID` in Railway to enable scheduled morning check-ins.",
        parse_mode="Markdown"
    )


async def set_morning_priorities(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ''
    lines = [l.strip() for l in text.replace('/morgen', '', 1).strip().split('\n') if l.strip()]

    if len(lines) != 3:
        await update.message.reply_text(
            '❌ Stuur precies 3 priorities:\n\n/morgen\nPriority 1\nPriority 2\nPriority 3'
        )
        return

    tz = pytz.timezone("Europe/Amsterdam")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).date()

    if DATABASE_URL:
        conn = _db_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO morning_priorities (date, p1, p2, p3)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE
                    SET p1 = EXCLUDED.p1, p2 = EXCLUDED.p2, p3 = EXCLUDED.p3, created_at = NOW()
                """, (tomorrow, lines[0], lines[1], lines[2]))
            conn.commit()
        finally:
            conn.close()

    await update.message.reply_text(
        f'✅ Priorities voor morgen ({tomorrow}) opgeslagen:\n\n1. {lines[0]}\n2. {lines[1]}\n3. {lines[2]}'
    )


DUTCH_DAYS = ['Maandag', 'Dinsdag', 'Woensdag', 'Donderdag', 'Vrijdag', 'Zaterdag', 'Zondag']
DUTCH_MONTHS = ['januari', 'februari', 'maart', 'april', 'mei', 'juni',
                'juli', 'augustus', 'september', 'oktober', 'november', 'december']
HABIT_META = [('walk', '🚶'), ('no_phone', '📵'), ('clients', '🔍')]


async def dag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = pytz.timezone("Europe/Amsterdam")
    today = datetime.now(tz).date()
    today_idx = today.weekday()  # Mon=0, Sun=6
    iso = today.isocalendar()
    week_key = f"{iso[0]}-W{iso[1]:02d}"
    date_str = f"{DUTCH_DAYS[today_idx]} {today.day} {DUTCH_MONTHS[today.month - 1]}"

    loop = asyncio.get_running_loop()

    # Calendar
    if has_calendar():
        tomorrow = (today + timedelta(days=1)).isoformat()
        calendar_raw = await loop.run_in_executor(
            None, fetch_calendar_events, today.isoformat(), tomorrow
        )
        cal_lines = [
            f"• {line.strip()[2:]}"
            for line in calendar_raw.split('\n')
            if line.strip().startswith('- ')
        ]
        calendar_block = '\n'.join(cal_lines) if cal_lines else '_Niets gepland_'
        calendar_summary = ', '.join(l[2:] for l in cal_lines) or 'geen agenda'
    else:
        calendar_block = '_Geen agenda gekoppeld_'
        calendar_summary = 'geen agenda'

    # Priorities
    prio_block = '_Nog geen priorities — stuur /morgen vanavond._'
    prio_summary = 'geen priorities ingesteld'
    if DATABASE_URL:
        conn = _db_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT p1, p2, p3 FROM morning_priorities WHERE date = %s", (today,)
                )
                row = cur.fetchone()
                if row:
                    prio_block = f"1. {row[0]}\n2. {row[1]}\n3. {row[2]}"
                    prio_summary = f"{row[0]}, {row[1]}, {row[2]}"
        finally:
            conn.close()

    # Habits — 🟣 done · ⬜ missed · ▫️ future
    habits_data = db_get_week_habits(week_key)
    habit_lines = []
    for habit_id, emoji in HABIT_META:
        week_row = habits_data.get(habit_id, [False] * 7)
        dots = []
        for i in range(7):
            if i > today_idx:
                dots.append('▫️')
            elif week_row[i]:
                dots.append('🟣')
            else:
                dots.append('⬜')
        habit_lines.append(f"{emoji}  {''.join(dots)}")
    habits_block = '\n'.join(habit_lines)

    # One closing line from TARS (direct API call, not saved to history)
    try:
        closing_resp = await loop.run_in_executor(
            None,
            lambda: anthropic_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=50,
                messages=[{"role": "user", "content": (
                    f"Today is {date_str}. Agenda: {calendar_summary}. "
                    f"Top 3: {prio_summary}. "
                    f"Write ONE closing line for Stef's day overview — "
                    f"max 10 words, specific to his actual day, honest, no fluff. "
                    f"Just the line, no quotes."
                )}]
            )
        )
        closing = closing_resp.content[0].text.strip().replace('_', '').replace('*', '')
    except Exception:
        closing = "Maak er wat van."

    msg = (
        f"☀️ *{date_str}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 *Agenda*\n{calendar_block}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 *Top 3*\n{prio_block}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Habits*\n{habits_block}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"_{closing}_"
    )

    try:
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(msg)


async def show_priorities(update: Update, context: ContextTypes.DEFAULT_TYPE):
    priorities = load_context("current-priorities.md")
    text = f"*Your current priorities:*\n\n{priorities}\n\n_Tell me to update them anytime._"
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text)


async def test_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sending a test morning check-in...")
    messages = [{"role": "user", "content": "Send me a short morning check-in. Pull up today's calendar first, then give me a brief, direct plan for the day."}]
    reply = await run_with_tools(messages, max_tokens=512)
    await update.message.reply_text(reply)


async def evening_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sending evening check-in...")
    messages = [{"role": "user", "content": "Send me a short evening check-in. First fetch tomorrow's weather with get_weather and check tomorrow's calendar. Then: one win from today (ask me to name it, or pick something from the calendar if obvious), one honest reflection worth sitting with before sleep, and close with a quick preview of tomorrow — what's on the schedule and the weather. Keep it tight, conversational, and with a bit of dry humour — not a report, not a pep talk."}]
    reply = await run_with_tools(messages, max_tokens=512)
    await update.message.reply_text(reply)


async def send_morning_checkin(bot):
    if not STEF_CHAT_ID:
        return
    loop = asyncio.get_running_loop()
    broken = await loop.run_in_executor(None, db_check_and_reset_missed_streaks)
    for habit_id, lost in broken:
        if lost >= 7:
            try:
                await bot.send_message(chat_id=int(STEF_CHAT_ID), text=f"{habit_id.capitalize()}streak gebroken na {lost} dagen. Vandaag opnieuw.")
            except Exception:
                pass
    streak_note = await loop.run_in_executor(None, db_get_streak_morning_note)
    streak_context = f" Streak info — add max 1 casual line if notable (no heading): {streak_note}" if streak_note else ""
    messages = [{"role": "user", "content": f"Good morning — check today's and tomorrow's calendar, then send me a morning message like a friend who already looked at my day. What's actually happening today, what's the one thing that matters most, and is there anything coming up I should prep for today.{streak_context} End with one short motivating or inspiring quote — from anyone: thinkers, athletes, artists, entrepreneurs — and include who said it. Keep it short and real, no report format."}]
    reply = await run_with_tools(messages, max_tokens=600)
    try:
        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply, parse_mode="Markdown")
    except Exception:
        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply)


async def send_evening_checkin(bot):
    if not STEF_CHAT_ID:
        return
    messages = [{"role": "user", "content": "Send me a short evening check-in. First fetch tomorrow's weather with get_weather and check tomorrow's calendar. Then: one win from today (ask me to name it, or pick something from the calendar if obvious), one honest reflection worth sitting with before sleep, and close with a quick preview of tomorrow — what's on the schedule and the weather. Keep it tight, conversational, and with a bit of dry humour — not a report, not a pep talk."}]
    reply = await run_with_tools(messages, max_tokens=512)
    try:
        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply, parse_mode="Markdown")
    except Exception:
        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply)


async def send_streak_reminder(bot, hour):
    if not STEF_CHAT_ID or not DATABASE_URL:
        return
    try:
        open_habits = db_get_open_habits()
        if not open_habits:
            return
        summary = db_get_streak_summary()
        habit_info = [f"{h} (streak: {summary.get(h, {}).get('streak', 0)})" for h in open_habits]
        if hour < 14:
            tone = "ONE casual offhand line — like someone who just happens to notice: 'je leesstreak loopt nog' or 'sport staat nog open vandaag'. No 'vergeet niet', no exclamation mark."
        elif hour < 19:
            tone = "ONE sentence — slightly more direct. Use the streak number if relevant: '5 dagen op rij — nog even.' No drama."
        else:
            hours_left = 23 - hour
            tone = f"Max 2 sentences with time pressure — nog {hours_left} uur, laatste kans vandaag. Vary the phrasing every time."
        messages = [{"role": "user", "content": f"It's {hour}:00. Open habits: {', '.join(habit_info)}. Send {tone}"}]
        reply = await run_with_tools(messages, max_tokens=120)
        try:
            await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply, parse_mode="Markdown")
        except Exception:
            await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply)
    except Exception as e:
        logger.error(f"streak_reminder failed: {e}")


async def schedule_daily_streak_reminders(bot, scheduler):
    import random
    from datetime import time as dt_time
    tz = pytz.timezone("Europe/Amsterdam")
    now = datetime.now(tz)
    today = now.date()
    num_reminders = random.choice([1, 2, 3])
    slots = list(range(480, 1380, 15))  # 08:00–23:00 in 15-min slots
    chosen = sorted(random.sample(slots, num_reminders))
    scheduled = []
    for minutes in chosen:
        hour, minute = divmod(minutes, 60)
        run_at = tz.localize(datetime.combine(today, dt_time(hour, minute)))
        if run_at > now:
            scheduler.add_job(send_streak_reminder, "date", run_date=run_at, args=[bot, hour])
            scheduled.append(f"{hour}:{minute:02d}")
    logger.info(f"Streak reminders today: {scheduled or 'none (all past)'}")


async def send_weekly_review(bot):
    if not STEF_CHAT_ID:
        return
    messages = [{"role": "user", "content": "It's Sunday evening — send me a short weekly review. Check next week's calendar, then tell me what to reflect on from this week and what the main focus should be for next week. Keep it tight and honest."}]
    reply = await run_with_tools(messages, max_tokens=768)
    try:
        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply, parse_mode="Markdown")
    except Exception:
        await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply)


async def post_init(application: Application):
    try:
        init_db()
    except Exception as e:
        logger.error(f"init_db failed: {e}")
    if STEF_CHAT_ID:
        scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Amsterdam"))
        scheduler.add_job(send_morning_checkin, "cron", hour=7, minute=0, args=[application.bot])
        scheduler.add_job(send_evening_checkin, "cron", day_of_week="mon-sat", hour=23, minute=0, args=[application.bot])
        scheduler.add_job(send_weekly_review, "cron", day_of_week="sun", hour=23, minute=0, args=[application.bot])
        scheduler.add_job(check_reminders, "interval", minutes=1, args=[application.bot])
        scheduler.add_job(check_deadlines, "cron", hour=8, minute=0, args=[application.bot])
        scheduler.add_job(schedule_daily_streak_reminders, "cron", hour=7, minute=5, args=[application.bot, scheduler])
        try:
            await schedule_daily_streak_reminders(application.bot, scheduler)
        except Exception as e:
            logger.error(f"schedule_daily_streak_reminders failed on startup: {e}")
        scheduler.start()
        application.bot_data["scheduler"] = scheduler
        logger.info("Scheduled: morning 07:00, evening 23:00 (Mon-Sat), weekly review 23:00 (Sun), streak reminders random")
    else:
        logger.info("STEF_CHAT_ID not set — scheduled messages disabled")


async def post_shutdown(application: Application):
    scheduler = application.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown()


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_checkin))
    app.add_handler(CommandHandler("evening", evening_checkin))
    app.add_handler(CommandHandler("priorities", show_priorities))
    app.add_handler(CommandHandler("morgen", set_morning_priorities))
    app.add_handler(CommandHandler("dag", dag_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
