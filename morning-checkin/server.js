import express from 'express';
import pg from 'pg';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import 'dotenv/config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

fs.mkdirSync(path.join(__dirname, 'data'), { recursive: true });

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

function loadJSON(filePath) {
  try {
    return JSON.parse(fs.readFileSync(path.join(__dirname, filePath), 'utf8'));
  } catch {
    return {};
  }
}

function saveJSON(filePath, data) {
  fs.writeFileSync(path.join(__dirname, filePath), JSON.stringify(data, null, 2));
}

function getWeekKey(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`;
}

// --- API ---

app.get('/api/priorities', async (req, res) => {
  const today = new Date().toISOString().split('T')[0];
  try {
    const result = await pool.query(
      'SELECT p1, p2, p3 FROM morning_priorities WHERE date = $1',
      [today]
    );
    if (result.rows.length === 0) return res.json([]);
    const { p1, p2, p3 } = result.rows[0];
    res.json([p1, p2, p3]);
  } catch (err) {
    console.error('DB priorities error:', err.message);
    res.json([]);
  }
});

app.get('/api/habits', async (req, res) => {
  const today = new Date();
  const weekKey = getWeekKey(today);

  try {
    const result = await pool.query(
      'SELECT habit_id, day_index, done FROM habits WHERE week_key = $1',
      [weekKey]
    );
    const habits = {
      walk:     [false, false, false, false, false, false, false],
      no_phone: [false, false, false, false, false, false, false],
      clients:  [false, false, false, false, false, false, false],
    };
    for (const row of result.rows) {
      if (habits[row.habit_id] !== undefined) {
        habits[row.habit_id][row.day_index] = row.done;
      }
    }
    res.json({ weekKey, habits });
  } catch (err) {
    console.error('DB habits error:', err.message);
    res.json({
      weekKey,
      habits: {
        walk:     [false, false, false, false, false, false, false],
        no_phone: [false, false, false, false, false, false, false],
        clients:  [false, false, false, false, false, false, false],
      },
    });
  }
});

app.post('/api/habits', async (req, res) => {
  const { habit, weekKey, dayIndex, value } = req.body;

  if (!['walk', 'no_phone', 'clients'].includes(habit)) {
    return res.status(400).json({ error: 'Invalid habit' });
  }

  try {
    await pool.query(
      `INSERT INTO habits (week_key, habit_id, day_index, done)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (week_key, habit_id, day_index) DO UPDATE SET done = EXCLUDED.done`,
      [weekKey, habit, dayIndex, value]
    );
    res.json({ ok: true });
  } catch (err) {
    console.error('DB set habit error:', err.message);
    res.status(500).json({ error: 'Failed to save' });
  }
});

app.get('/api/quote', async (req, res) => {
  const today = new Date().toISOString().split('T')[0];
  const cache = loadJSON('data/quote_cache.json');

  if (cache[today]) return res.json(cache[today]);

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-6',
        max_tokens: 150,
        messages: [
          {
            role: 'user',
            content: `Seed: ${today}. Generate a unique motivational quote for a creative design student building his career. Focus on creativity, making things, or showing up consistently. Return ONLY valid JSON, no markdown: {"quote": "...", "author": "..."}`,
          },
        ],
      }),
    });

    const apiData = await response.json();
    const parsed = JSON.parse(apiData.content[0].text.trim());

    cache[today] = parsed;
    saveJSON('data/quote_cache.json', cache);
    res.json(parsed);
  } catch (err) {
    console.error('Quote error:', err.message);
    res.json({
      quote: "You don't have to be great to start, but you have to start to be great.",
      author: 'Zig Ziglar',
    });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Morning check-in → http://localhost:${PORT}`));
