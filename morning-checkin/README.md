# Morning Check-in

Daily check-in page. Opens in the browser every morning — habits, priorities from TARS, daily quote.

## Setup

```bash
cd morning-checkin
npm install
cp .env.example .env
# Fill in .env
npm start
# Open http://localhost:3000
```

## .env values

| Key | Where to get it |
|-----|----------------|
| `DATABASE_URL` | Railway → your Postgres service → Variables → DATABASE_URL |
| `ANTHROPIC_API_KEY` | Same key you already use for TARS |

## How priorities work

The night before, send this to TARS:

```
/morgen
Finish product design case study
Reply to 3 potential clients
30 min walk before noon
```

TARS saves them to the shared Postgres database. Next morning when you open the page, they're pre-filled.
