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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id SERIAL PRIMARY KEY,
                    message TEXT NOT NULL,
                    remind_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
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


def db_set_reminder(message, remind_at_str):
    tz = pytz.timezone("Europe/Amsterdam")
    remind_at = datetime.strptime(remind_at_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reminders (message, remind_at) VALUES (%s, %s)",
                (message, remind_at)
            )
        conn.commit()
    finally:
        conn.close()


async def check_reminders(bot):
    if not DATABASE_URL or not STEF_CHAT_ID:
        return
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
            for reminder_id, message in due:
                await bot.send_message(chat_id=int(STEF_CHAT_ID), text=f"Reminder: {message}")
                cur.execute("UPDATE reminders SET sent = TRUE WHERE id = %s", (reminder_id,))
        conn.commit()
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
            start_dt = datetime.fromisoformat(f"{date}T{start_time}").replace(tzinfo=tz)
            if end_time:
                end_dt = datetime.fromisoformat(f"{date}T{end_time}").replace(tzinfo=tz)
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
        tools.append(CREATE_EVENT_TOOL)
    if has_search():
        tools.append(SEARCH_TOOL)
    if DATABASE_URL:
        tools.extend([SAVE_MEMORY_TOOL, UPDATE_CONTEXT_TOOL, REMINDER_TOOL])

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
                    elif block.name == "set_reminder":
                        await loop.run_in_executor(
                            None, db_set_reminder, block.input["message"], block.input["remind_at"]
                        )
                        result = f"Reminder set for {block.input['remind_at']}: {block.input['message']}"
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
        scheduler.add_job(check_reminders, "interval", minutes=1, args=[application.bot])
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
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
