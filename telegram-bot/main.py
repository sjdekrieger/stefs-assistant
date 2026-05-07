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


def get_calendar_context(days=2):
    try:
        service = build("calendar", "v3", credentials=get_google_creds(), cache_discovery=False)
        tz = pytz.timezone("Europe/Amsterdam")
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=days)

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
            return "No events in the next 2 days."

        today = start.date()
        tomorrow = (start + timedelta(days=1)).date()

        events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
        lines = []
        current_day = None
        for e in events:
            title = e.get("summary", "Untitled")
            start_raw = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start_raw:
                event_dt = datetime.fromisoformat(start_raw).astimezone(tz)
                event_date = event_dt.date()
                t = event_dt.strftime("%H:%M")
                time_str = t
            else:
                event_date = datetime.fromisoformat(start_raw).date()
                time_str = "All day"

            if event_date != current_day:
                current_day = event_date
                if event_date == today:
                    lines.append("Today:")
                elif event_date == tomorrow:
                    lines.append("Tomorrow:")
            lines.append(f"  - {time_str} — {title}")
        return "\n".join(lines)
    except Exception as e:
        import traceback
        logger.error(f"Calendar fetch failed: {e}\n{traceback.format_exc()}")
        return ""


def get_system_prompt(include_calendar=True):
    date = datetime.now(pytz.timezone("Europe/Amsterdam")).strftime("%Y-%m-%d, %A")
    prompt = SYSTEM_PROMPT.format(date=date)
    has_token = bool(os.environ.get("GOOGLE_REFRESH_TOKEN"))
    logger.info(f"Calendar: include={include_calendar}, has_token={has_token}")
    if include_calendar and has_token:
        calendar = get_calendar_context()
        logger.info(f"Calendar context: {repr(calendar[:100]) if calendar else 'empty'}")
        if calendar:
            prompt += f"\n\n## Today's Calendar\n{calendar}"
    return prompt


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Hey Stef, I'm online.\n\nYour chat ID is: `{chat_id}`\n\nAdd this as `STEF_CHAT_ID` in Railway to enable scheduled morning check-ins.",
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text

    if chat_id not in conversation_histories:
        conversation_histories[chat_id] = []

    conversation_histories[chat_id].append({"role": "user", "content": user_message})

    if len(conversation_histories[chat_id]) > 20:
        conversation_histories[chat_id] = conversation_histories[chat_id][-20:]

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=get_system_prompt(),
        messages=conversation_histories[chat_id]
    )

    reply = response.content[0].text
    conversation_histories[chat_id].append({"role": "assistant", "content": reply})

    await update.message.reply_text(reply)


async def send_morning_checkin(bot):
    if not STEF_CHAT_ID:
        return

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=get_system_prompt(),
        messages=[{
            "role": "user",
            "content": "Send me a short morning check-in. Brief, direct — what should I keep in mind and focus on today?"
        }]
    )

    await bot.send_message(chat_id=int(STEF_CHAT_ID), text=response.content[0].text)


async def send_evening_checkin(bot):
    if not STEF_CHAT_ID:
        return

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=get_system_prompt(),
        messages=[{
            "role": "user",
            "content": "Send me a short evening check-in. Brief reflection — what's worth thinking about before I wind down?"
        }]
    )

    await bot.send_message(chat_id=int(STEF_CHAT_ID), text=response.content[0].text)


async def send_weekly_review(bot):
    if not STEF_CHAT_ID:
        return

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=768,
        system=get_system_prompt(),
        messages=[{
            "role": "user",
            "content": "It's Sunday evening — send me a short weekly review. What should I reflect on from this week, and what's the main focus for next week? Keep it tight and honest."
        }]
    )

    await bot.send_message(chat_id=int(STEF_CHAT_ID), text=response.content[0].text)


async def post_init(application: Application):
    if STEF_CHAT_ID:
        scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Amsterdam"))
        scheduler.add_job(
            send_morning_checkin,
            "cron",
            hour=7,
            minute=0,
            args=[application.bot]
        )
        scheduler.add_job(
            send_evening_checkin,
            "cron",
            day_of_week="mon-sat",
            hour=23,
            minute=0,
            args=[application.bot]
        )
        scheduler.add_job(
            send_weekly_review,
            "cron",
            day_of_week="sun",
            hour=23,
            minute=0,
            args=[application.bot]
        )
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
