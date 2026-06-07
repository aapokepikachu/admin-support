# admin-support

A production-ready Telegram support-relay bot.  
Users message the bot privately → messages are forwarded to an admin group → admin replies route back to users.

**Stack:** Python 3.11 · aiogram v3 · aiohttp webhook server · Motor (async MongoDB)  
**Hosting:** Render **free Web Service** + MongoDB Atlas **free M0 cluster**

---

## How it works

```
User (private chat)          Bot (Render Web Service)        Admin Group
       │                              │                            │
       │── any message ──────────────►│                            │
       │                              │── msg.forward() ──────────►│  ← true forward
       │                              │   [mapping saved to DB]    │    admins see sender
       │                              │                            │
       │                              │◄── reply to forwarded ─────│
       │◄─ bot.copy_message() ────────│                            │
       │   (admin reply delivered)    │                            │
```

1. User sends any message in private chat.
2. Bot calls `msg.forward()` to the admin group — a **true Telegram forward**, so admins see the original sender's name and avatar.
3. The forwarded message's ID is stored in MongoDB alongside the user's ID.
4. When an admin **replies** to that forwarded message, the bot looks up the mapping, finds the user, and delivers the reply via `bot.copy_message()`.
5. Admin-only messages (not replies to forwarded messages) are ignored — no double-forwarding, no leaking internal discussion.

---

## Features

| Feature | Details |
|---|---|
| Message relay | True forward (preserves sender metadata) + reply routing back to user |
| Anti-spam | Configurable rate limit: N messages / window, then cooldown block |
| Captcha | Optional inline button captcha for new users; toggled by admins |
| Ban system | `/ban`, `/unban`, `/banlist` — usable by all admin group members |
| Broadcast | Send a message to all non-deleted users |
| Report deep-links | Admin-created report templates with Proceed/Cancel, Done/Invalid flows |
| Allowed channels | Whitelist for `/report` link validation |
| Group guard | Bot auto-leaves any group that is not the configured admin group |

---

## Project structure

```
admin-support/
├── main.py                      # aiohttp webhook server + bot wiring
├── config.py                    # Typed settings loaded from env vars
├── db.py                        # Motor client, startup, index creation
├── requirements.txt
├── render.yaml                  # Render web service manifest
├── .env.example
│
├── handlers/
│   ├── user.py                  # /start /help /ping /report + message forwarding
│   ├── admin.py                 # Admin commands + reply-to-user routing
│   ├── report.py                # /reportgen FSM + all report callbacks
│   ├── captcha.py               # Captcha callback answer handler
│   └── group_guard.py           # Auto-leave non-admin groups
│
├── middlewares/
│   ├── rate_limit.py            # Ban check + rate limiting (runs before captcha)
│   └── captcha.py               # Blocks messages until captcha is solved
│
├── services/                    # Pure DB logic — no Telegram types
│   ├── user_service.py
│   ├── ban_service.py
│   ├── message_map_service.py
│   ├── rate_limit_service.py
│   ├── captcha_service.py
│   ├── channel_service.py
│   └── report_service.py
│
└── utils/
    └── helpers.py               # parse_channel_id
```

---

## MongoDB schema

### `users`
```json
{
  "user_id": 123456789,
  "username": "johndoe",
  "first_name": "John",
  "last_name": "Doe",
  "joined_at": "<ISODate>",
  "last_seen": "<ISODate>",
  "status": "active | banned | deleted",
  "is_deleted": false,
  "captcha_passed": true
}
```

### `bans`
```json
{ "user_id": 123456789, "banned_by": 987654321, "banned_at": "<ISODate>" }
```

### `message_map`
Indexed on `admin_msg_id` for O(1) reply routing.
```json
{
  "user_id": 123456789,
  "user_msg_id": 42,
  "admin_msg_id": 101,
  "created_at": "<ISODate>"
}
```

### `rate_limit`
```json
{
  "user_id": 123456789,
  "count": 3,
  "window_start": "<ISODate>",
  "throttled_until": null
}
```

### `captcha_sessions`
```json
{
  "user_id": 123456789,
  "question": "What is 3 + 4?",
  "answer": "7",
  "options": ["5", "6", "7", "8", "9"],
  "created_at": "<ISODate>"
}
```

### `allowed_channels`
```json
{ "channel_id": -1001234567890, "title": "My Channel" }
```

### `report_templates`
```json
{
  "_id": "<ObjectId>",
  "title": "Hoppa link",
  "slug": "abc12345",
  "prompt_msg": "Do you want to report that Movie Hoppa is not working?",
  "invalid_msg": "The Movie Hoppa link is working fine.",
  "done_msg": "The movie link has been fixed.",
  "created_at": "<ISODate>"
}
```

### `report_states`
```json
{
  "user_id": 123456789,
  "template_id": "<ObjectId>",
  "status": "pending | done | invalid",
  "admin_msg_id": 202,
  "submitted_at": "<ISODate>",
  "resolved_at": "<ISODate>"
}
```

### `settings`
```json
{ "key": "captcha", "enabled": false }
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | BotFather token |
| `ADMIN_GROUP_ID` | ✅ | — | Integer ID of the admin supergroup, e.g. `-1001234567890` |
| `MONGO_URI` | ✅ | — | MongoDB Atlas connection string |
| `WEBHOOK_HOST` | ✅ | — | Your Render HTTPS URL, e.g. `https://admin-support.onrender.com` |
| `DB_NAME` | ❌ | `supportbot` | MongoDB database name |
| `PORT` | ❌ | `8000` | Injected automatically by Render — do not set manually |
| `RATE_LIMIT_MESSAGES` | ❌ | `5` | Max messages allowed per window |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | Window duration in seconds |
| `RATE_LIMIT_COOLDOWN` | ❌ | `300` | Cooldown block duration in seconds |

---

## Local setup

```bash
git clone <your-repo>
cd admin-support

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Fill in BOT_TOKEN, ADMIN_GROUP_ID, MONGO_URI
# For local testing, set WEBHOOK_HOST to an ngrok URL (see below)

python main.py
```

### Local webhook with ngrok
Telegram requires a public HTTPS URL. Use [ngrok](https://ngrok.com/) for local testing:

```bash
ngrok http 8000
# Copy the https://xxxx.ngrok.io URL into WEBHOOK_HOST in your .env
```

---

## Render deployment (free Web Service)

> **Why Web Service and not Background Worker?**  
> Render's Background Worker tier is **paid** (starts at $7/month).  
> The free tier only covers **Web Services** and static sites.  
> This bot runs as a webhook server (aiohttp), which is a web service — exactly what the free tier provides.

> **Why is Python 3.11 pinned?**  
> Render currently defaults to Python 3.14. `pydantic-core` (required by aiogram) has no prebuilt wheel for 3.14 and must compile from Rust — which fails on Render's read-only filesystem.  
> The repo contains a `.python-version` file (`3.11.11`) and `render.yaml` sets `PYTHON_VERSION=3.11.11`. Both are required; together they force Render to use Python 3.11 where all dependencies have prebuilt wheels.

### Step 1 — MongoDB Atlas (free M0)

1. Go to [cloud.mongodb.com](https://cloud.mongodb.com) → create a free account.
2. Create a **free M0 cluster** (512 MB, shared).
3. Under *Database Access* → add a user with read/write permissions.
4. Under *Network Access* → add `0.0.0.0/0` (required because Render's IPs are dynamic).
5. Click *Connect* → *Drivers* → copy the connection string.  
   Replace `<password>` with your DB user's password.

### Step 2 — Push code to GitHub

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/you/admin-support.git
git push -u origin main
```

### Step 3 — Create Render Web Service

1. Go to [dashboard.render.com](https://dashboard.render.com) → **New → Web Service**.
2. Connect your GitHub repository.
3. Settings:
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `python main.py`
   - **Plan:** Free
4. Add environment variables (under the *Environment* tab):

   | Key | Value |
   |---|---|
   | `BOT_TOKEN` | your bot token |
   | `ADMIN_GROUP_ID` | e.g. `-1001234567890` |
   | `MONGO_URI` | your Atlas connection string |
   | `WEBHOOK_HOST` | leave blank for now — see Step 4 |

5. Click **Deploy**.

### Step 4 — Set WEBHOOK_HOST

After the first deploy, Render assigns your service a URL like `https://admin-support.onrender.com`.

1. Copy that URL.
2. Go to **Environment** in your Render dashboard.
3. Add: `WEBHOOK_HOST` = `https://admin-support.onrender.com` (no trailing slash).
4. Click **Save** — Render redeploys automatically.

The bot will set the Telegram webhook on startup and is now live.

### Step 5 — Keep the service awake (UptimeRobot)

Render free web services **sleep after 15 minutes of inactivity**. The bot exposes a `/health` endpoint specifically to prevent this.

1. Go to [uptimerobot.com](https://uptimerobot.com) → create a free account.
2. **New Monitor** → HTTP(s).
3. URL: `https://admin-support.onrender.com/health`
4. Interval: **5 minutes**.
5. Save.

UptimeRobot pings `/health` every 5 minutes, keeping the service awake 24/7 at no cost.

---

## Getting the admin group ID

1. Make your group a **supergroup** (Settings → Group type → Supergroup).
2. Add [@RawDataBot](https://t.me/RawDataBot) to the group.
3. It replies with the chat ID, e.g. `-1001234567890`.
4. Use that value as `ADMIN_GROUP_ID`.

---

## User commands

| Command | Description |
|---|---|
| `/start` | Welcome message with relay explanation, rate-limit rules, and captcha notice |
| `/help` | Brief list of user commands |
| `/report` | Start a broken-link report flow for an authorised channel |
| `/reportlist` | View your active reports and remaining quota |
| `/ping` | Replies with "Pong" and round-trip latency in ms |
| `/about` | Shows bot version and credits |

## Admin commands (admin group only, all members)

| Command | Description |
|---|---|
| `/helpa` | List all admin commands |
| `/ban` | Reply to a forwarded user message to ban that user |
| `/unban <id or @username>` | Unban a user |
| `/banlist` | List all banned users |
| `/users` | List all registered users with status |
| `/broadcast` | Reply to a message to broadcast it to all active users |
| `/setchannel add <id> [title]` | Whitelist a channel for report validation |
| `/setchannel remove <id>` | Remove a channel from the whitelist |
| `/setchannel list` | Show all whitelisted channels |
| `/reportgen` | Open the report link generator (Create / Edit / Delete) |
| `/captcha on\|off` | Toggle captcha for new users |
| `/db` | Show MongoDB health stats + management buttons (delete templates, clear maps, reset captcha, wipe DB) |
| `/setreportcount <n>` | Set the maximum number of active `/report` submissions per user (default: 2) |
| `/reportlist` | View all users' active link reports |

---

## Credits

Made by [@PokemonBots](https://t.me/PokemonBots)

---

## Caveats and free-tier limitations

| Limitation | Details |
|---|---|
| **Render free: 15-min sleep** | Mitigated by UptimeRobot pinging `/health` every 5 min. Without it, the bot stops responding when the service sleeps. |
| **Render free: 512 MB RAM** | Bot uses ~40–80 MB under normal load. Well within limits. |
| **Render free: cold start on first ping after sleep** | If UptimeRobot is set up, this should not happen in practice. |
| **MongoDB Atlas M0: 512 MB storage** | Sufficient for thousands of users. Monitor with `/db`. Add a 30-day TTL index on `message_map.created_at` if storage becomes a concern. |
| **MongoDB Atlas M0: shared cluster** | Occasional latency spikes possible. All DB calls are async so the bot stays responsive. |
| **FSM in memory** | The `/reportgen` create/edit flow uses aiogram's in-memory FSM. If Render restarts the service (deploys, OOM), any in-progress flow is lost and the admin must restart it. For persistent FSM, swap `MemoryStorage` for a MongoDB-backed storage. |
| **Broadcast rate** | Telegram limits bots to ~30 messages/second. Large broadcasts will take time; the bot does not implement flood-control delays by design to keep memory usage minimal. |
| **t.me links in /setchannel** | t.me links cannot be resolved to a numeric ID without an extra API call. Use the raw numeric channel ID (e.g. `-1001234567890`) with `/setchannel add`. |
