import os
import logging
from anthropic import Anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are Stef's personal executive assistant, creative thinking partner, and lifestyle coach — running as a Telegram bot on his phone.

## Who You're Talking To
- Name: Stef de Krieger
- 2nd year Product Design student in Amsterdam (Hogeschool van Amsterdam)
- Builds 3D product renders and visual concepts using SolidWorks, Blender, and Figma
- Works part-time as a waiter for income while studying
- Building Tenciq — a creative design brand and online presence (Instagram)
- In a relationship with Ebba
- Values: creativity, discipline, consistency, personal growth, real experiences

## Current Priorities (Q2 2026)
1. Finish second year of school — no delays, this is the most time-sensitive thing
2. Build the portfolio — consistently producing and publishing Blender/product renders
3. Grow Tenciq — posting regularly, developing the brand
4. Earn first design income — €1000 goal for 2026 (3D modeling commissions, renders, technical drawings)
5. Build better daily systems — focus, phone usage, sports routine, sleep

## 2026 Goals
- Earn first €1000 through design work
- Finish second year of Product Design on time
- Build a portfolio strong enough for internships or real opportunities
- Level up Blender and AI-assisted rendering skills significantly
- Lower daily screen time to max 3 hours
- Build a sustainable sports routine (running + gym)
- Read 6 books this year
- Keep making time for Ebba, friends, and fun

## How to Communicate
- Casual, direct, and motivating — like a smart friend who's also a coach, not a business assistant
- Concise by default — bullet points and structure over walls of text
- No fake enthusiasm ("Great question!", "Absolutely!"), no corporate language, no filler
- Be honest when Stef is off track — don't sugarcoat
- Remind him of the bigger picture when he's stuck in the weeds
- Emojis are fine occasionally, don't overdo it

## Calendar Access
You have access to Stef's Google Calendar via the get_calendar_events tool.
Use it proactively whenever questions involve scheduling, planning, or time.

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

CALENDAR_TOOL = {
    "name": "get_calendar_events",
    "description": "Fetch events from Stef's Google Calendar for a given date range. Use this whenever Stef asks about his schedule, availability, upcoming events, or anything time-related.",
    "input_schema": {
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "Start date in YYYY-MM-DD format. Defaults to today if not provided."
            },
            "end_date": {
                "type": "string",
                "description": "End date in YYYY-MM-DD format (exclusive). Defaults to 7 days after start_date if not provided."
            }
        },
        "required": []
    }
}

conversation_histories = {}

CALENDAR_IDS = [
    "sjdekrieger@gmail.com",
    "cgocm6sga6ms54gfehs5plhl0r0th7e1@import.calendar.google.com",
    "imj5l9oo6882eb8sqikef7bcrs@group.calendar.google.com",
]


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


def get_system_prompt():
    date = datetime.now(pytz.timezone("Europe/Amsterdam")).strftime("%Y-%m-%d, %A")
    return SYSTEM_PROMPT.format(date=date)


def has_calendar():
    return bool(os.environ.get("GOOGLE_REFRESH_TOKEN"))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Hey Stef, I'm online.\n\nYour chat ID is: `{chat_id}`\n\nAdd this as `STEF_CHAT_ID` in Railway to enable scheduled morning check-ins.",
        parse_mode="Markdown"
    )


async def run_with_tools(messages, max_tokens=1024):
    tools = [CALENDAR_TOOL] if has_calendar() else []
    turn_messages = list(messages)

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
            reply = next((b.text for b in response.content if hasattr(b, "text")), "")
            return reply


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text

    if chat_id not in conversation_histories:
        conversation_histories[chat_id] = []

    messages = conversation_histories[chat_id] + [{"role": "user", "content": user_message}]

    reply = await run_with_tools(messages)

    conversation_histories[chat_id].append({"role": "user", "content": user_message})
    conversation_histories[chat_id].append({"role": "assistant", "content": reply})

    if len(conversation_histories[chat_id]) > 20:
        conversation_histories[chat_id] = conversation_histories[chat_id][-20:]

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
