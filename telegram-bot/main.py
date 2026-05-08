import os
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

SYSTEM_PROMPT_TEMPLATE = """You are Stef's personal executive assistant, creative thinking partner, and lifestyle coach — running as a Telegram bot on his phone.

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

## How to Communicate
- Casual, direct, and motivating — like a smart friend who's also a coach, not a business assistant
- Concise by default — bullet points and structure over walls of text
- No fake enthusiasm ("Great question!", "Absolutely!"), no corporate language, no filler
- Be honest when Stef is off track — don't sugarcoat
- Remind him of the bigger picture when he's stuck in the weeds
- Emojis are fine occasionally, don't overdo it

## Tools You Have
- **get_calendar_events**: Read Stef's Google Calendar for any date range — use proactively for planning
- **save_memory**: Persistently remember something across all future conversations — use this proactively when Stef shares something important (preferences, decisions, personal details, recurring patterns). Don't wait to be asked.
- **update_context**: Update Stef's current priorities or goals directly — use when he explicitly asks to update them

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

Today's date: {date}
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
    date = datetime.now(pytz.timezone("Europe/Amsterdam")).strftime("%Y-%m-%d, %A")
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


def get_google_creds():
    creds = Credentials(
        token=None,
        refresh_token=os.environ.get("GOOGLE_REFRESH_TOKEN"),
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
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
            except Exception:
                pass

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

SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": "Save a piece of information to persistent memory. This persists across all future conversations and restarts. Use proactively when Stef shares something important — preferences, decisions, personal facts, recurring patterns. Don't wait to be asked.",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "What to remember. Be specific and include context — e.g. 'Stef prefers short bullet responses over long paragraphs' rather than just 'prefers bullets'."}
        },
        "required": ["content"]
    }
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
    tools = []
    if has_calendar():
        tools.append(CALENDAR_TOOL)
    if DATABASE_URL:
        tools.extend([SAVE_MEMORY_TOOL, UPDATE_CONTEXT_TOOL])

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
                    elif block.name == "save_memory":
                        await loop.run_in_executor(None, db_save_memory, block.input["content"])
                        result = f"Saved to memory: {block.input['content']}"
                    elif block.name == "update_context":
                        await loop.run_in_executor(
                            None, db_update_context, block.input["section"], block.input["content"]
                        )
                        result = f"Updated {block.input['section']}."
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text
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

    await update.message.reply_text(reply)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Hey Stef, I'm online.\n\nYour chat ID is: `{chat_id}`\n\nAdd this as `STEF_CHAT_ID` in Railway to enable scheduled morning check-ins.",
        parse_mode="Markdown"
    )


async def test_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sending a test morning check-in...")
    messages = [{"role": "user", "content": "Send me a short morning check-in. Pull up today's calendar first, then give me a brief, direct plan for the day."}]
    reply = await run_with_tools(messages, max_tokens=512)
    await update.message.reply_text(reply)


async def evening_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sending evening check-in...")
    messages = [{"role": "user", "content": "Send me a short evening check-in. Brief reflection — what's worth thinking about before I wind down?"}]
    reply = await run_with_tools(messages, max_tokens=512)
    await update.message.reply_text(reply)


async def send_morning_checkin(bot):
    if not STEF_CHAT_ID:
        return
    messages = [{"role": "user", "content": "Send me a short morning check-in. Pull up today's calendar first, then give me a brief, direct plan for the day."}]
    reply = await run_with_tools(messages, max_tokens=512)
    await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply)


async def send_evening_checkin(bot):
    if not STEF_CHAT_ID:
        return
    messages = [{"role": "user", "content": "Send me a short evening check-in. Brief reflection — what's worth thinking about before I wind down?"}]
    reply = await run_with_tools(messages, max_tokens=512)
    await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply)


async def send_weekly_review(bot):
    if not STEF_CHAT_ID:
        return
    messages = [{"role": "user", "content": "It's Sunday evening — send me a short weekly review. Check next week's calendar, then tell me what to reflect on from this week and what the main focus should be for next week. Keep it tight and honest."}]
    reply = await run_with_tools(messages, max_tokens=768)
    await bot.send_message(chat_id=int(STEF_CHAT_ID), text=reply)


async def post_init(application: Application):
    init_db()
    if STEF_CHAT_ID:
        scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Amsterdam"))
        scheduler.add_job(send_morning_checkin, "cron", hour=7, minute=0, args=[application.bot])
        scheduler.add_job(send_evening_checkin, "cron", day_of_week="mon-sat", hour=23, minute=0, args=[application.bot])
        scheduler.add_job(send_weekly_review, "cron", day_of_week="sun", hour=23, minute=0, args=[application.bot])
        scheduler.start()
        application.bot_data["scheduler"] = scheduler
        logger.info("Scheduled: morning 07:00, evening 23:00 (Mon-Sat), weekly review 23:00 (Sun)")
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
