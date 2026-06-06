# Support Relay Bot

A production-ready Telegram support bot that relays private user messages to an admin group and routes admin replies back to users.

Built with **Python 3.11 · aiogram v3 · Motor (async MongoDB)**.  
Designed to run on **Render free tier** + **MongoDB Atlas free tier (512 MB)**.

---

## Features

| Category | Details |
|---|---|
| **Relay** | Forwards user messages to admin group via true Telegram forward (preserves sender metadata). Admin replies are routed back to the user. |
| **Anti-spam** | Configurable rate limiting: N messages per window, then a cooldown block. |
| **Captcha** | Optional inline captcha for new users before their first message. |
| **Ban system** | `/ban`, `/unban`, `/banlist` — all members of the admin group can moderate. |
| **Broadcast** | Send a message to all non-deleted users at once. |
| **Report links** | Deep-link report flow with admin-defined prompts, Done/Invalid inline buttons, and anti-spam state tracking. |
| **Group guard** | Bot auto-leaves any group that is not the configured admin group. |
| **Allowed channels** | Admins whitelist channels/groups; `/report` links only validate against those. |

---

## Project Structure

```
tgbot/
├── main.py                  # Entry point — bot + dispatcher setup
├── config.py                # Settings loaded from env vars
├── db.py                    # Motor client, index creation
├── requirements.txt
├── render.yaml              # Render deployment manifest
├── .env.example
│
├── handlers/
│   ├── user.py              # /start /help /ping /report + message forwarding
│   ├── admin.py             # All admin group commands + reply routing
│   ├── report.py            # /reportgen FSM + report proceed/cancel/done/invalid
│   ├── captcha.py           # Captcha callback answer handler
│   └── group_guard.py       # Auto-leave foreign groups
│
├── middlewares/
│   ├── rate_limit.py        # Per-user message rate limiting
│   └── captcha.py           # Blocks messages until captcha solved
│
├── services/
│   ├── user_service.py      # User CRUD
│   ├── ban_service.py       # Ban / unban / check
│   ├── message_map_service.py  # Forward→user mapping
│   ├── rate_limit_service.py   # Rate limit state
│   ├── captcha_service.py   # Captcha sessions + enable/disable
│   ├── channel_service.py   # Allowed channel list
│   └── report_service.py    # Report templates + states
│
└── utils/
    └── tg_helpers.py        # user_mention, extract_channel_id_from_link
```

---

## MongoDB Schema

### `users`
```json
{
  "user_id": 123456789,
  "username": "johndoe",
  "first_name": "John",
  "last_name": "Doe",
  "joined_at": "ISODate",
  "last_seen": "ISODate",
  "status": "active | banned | deleted",
  "is_deleted": false,
  "captcha_passed": true
}
```

### `bans`
```json
{ "user_id": 123456789, "banned_by": 987654321, "banned_at": "ISODate" }
```

### `message_map`
```json
{
  "user_id": 123456789,
  "user_msg_id": 42,
  "admin_msg_id": 101,
  "created_at": "ISODate"
}
```
> Indexed on `admin_msg_id` for O(1) reply routing.

### `rate_limit`
```json
{
  "user_id": 123456789,
  "count": 3,
  "window_start": "ISODate",
  "throttled_until": null
}
```

### `captcha_sessions`
```json
{
  "user_id": 123456789,
  "question": "What is 3 + 4?",
  "answer": "7",
  "options": ["5","6","7","8","9"],
  "created_at": "ISODate"
}
```

### `allowed_channels`
```json
{ "channel_id": -1001234567890, "title": "My Channel" }
```

### `report_templates`
```json
{
  "_id": "ObjectId",
  "title": "Hoppa link",
  "slug": "abc12345",
  "prompt_msg": "Do you want to report that Movie Hoppa is not working?",
  "invalid_msg": "The Movie Hoppa link is working fine.",
  "done_msg": "The movie link has been fixed.",
  "created_at": "ISODate"
}
```

### `report_states`
```json
{
  "user_id": 123456789,
  "template_id": "ObjectId",
  "status": "pending | done | invalid",
  "admin_msg_id": 202,
  "submitted_at": "ISODate",
  "resolved_at": "ISODate"
}
```

### `settings`
```json
{ "key": "captcha", "enabled": false }
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | BotFather token |
| `ADMIN_GROUP_ID` | ✅ | — | Integer ID of admin supergroup (e.g. `-1001234567890`) |
| `MONGO_URI` | ✅ | — | MongoDB Atlas connection string |
| `DB_NAME` | ❌ | `supportbot` | MongoDB database name |
| `RATE_LIMIT_MESSAGES` | ❌ | `5` | Max messages per window |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | Window size in seconds |
| `RATE_LIMIT_COOLDOWN` | ❌ | `300` | Cooldown duration in seconds after exceeding limit |

---

## Local Setup

```bash
git clone <your-repo>
cd tgbot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your real values

python main.py
```

---

## Render Deployment

1. **Create a MongoDB Atlas account** → New Project → Free M0 cluster.  
   - Create a DB user and allow access from `0.0.0.0/0` (required for Render's dynamic IPs).  
   - Copy the connection string into `MONGO_URI`.

2. **Push your code** to a GitHub/GitLab repository.

3. **Create a new Render service**:
   - Dashboard → *New* → *Background Worker*
   - Connect your repository
   - Runtime: **Python 3**
   - Build command: `pip install -r requirements.txt`
   - Start command: `python main.py`
   - Plan: **Free**

4. **Add environment variables** in Render's dashboard (or let `render.yaml` pre-fill them — you'll still need to set secret values manually).

5. Deploy. The bot uses **long polling** — no port or inbound network is needed, making it ideal for Render's free worker tier.

---

## Getting the Admin Group ID

1. Add [@userinfobot](https://t.me/userinfobot) or [@RawDataBot](https://t.me/RawDataBot) to your admin group.
2. It will print the group's integer ID, e.g. `-1001234567890`.
3. Use that as `ADMIN_GROUP_ID`.

---

## How the Forwarding / Reply System Works

```
User                       Bot                       Admin Group
 │                          │                              │
 │── "Hello, need help" ──► │                              │
 │                          │── forward(msg) ─────────────►│  [message_map saved]
 │                          │                              │
 │                          │◄─ reply to forwarded msg ────│
 │                          │   (admin types reply)        │
 │◄─ copy_message ──────────│                              │
 │   (bot delivers reply)   │                              │
```

1. **User → Bot**: The user sends any message in private chat. The bot calls `msg.forward(admin_group_id)` — this is a **true Telegram forward**, so admins see the original sender's name, avatar, and "Forwarded from" header.
2. **Mapping saved**: The forwarded message's `message_id` in the admin group is stored in `message_map` alongside the original `user_id`.
3. **Admin → User**: When an admin **replies** to that forwarded message, the bot looks up `message_map` by the replied-to `message_id`, finds the user, and calls `bot.copy_message()` to deliver the reply. This prevents double-forwarding and keeps admin-internal messages private.
4. **Loop prevention**: The admin reply handler only triggers on messages that are replies **and** whose reply-target exists in `message_map`. Plain admin messages are ignored.

---

## Caveats & Free Tier Limitations

| Limitation | Impact |
|---|---|
| **Render free worker sleeps after 15 min inactivity** | Long polling keeps the connection alive as long as the process is running; Render free workers do *not* sleep while the process is active — only web services sleep. Workers run continuously. ✅ |
| **Render free tier: 512 MB RAM** | The bot uses ~40–80 MB under normal load. Safe. ✅ |
| **MongoDB Atlas M0: 512 MB storage** | Sufficient for thousands of users. Monitor via `/db`. |
| **MongoDB Atlas M0: 100 max connections** | Motor uses a connection pool; default is well within limits. ✅ |
| **Broadcast may be slow** | Telegram rate-limits `sendMessage` to ~30 msg/s per bot. Large broadcasts will take time. No async flood control implemented by design (keeps memory low). |
| **Message map grows unbounded** | Old mappings are never pruned. Add a TTL index on `created_at` (e.g. 30 days) if storage becomes a concern: `db.message_map.createIndex({"created_at":1},{expireAfterSeconds:2592000})` |
| **No webhook** | Long polling is simpler and more reliable on free-tier workers with no static IP. |
| **FSM storage** | aiogram's default FSM storage is in-memory. On Render free tier, the process may restart. If a restart happens mid-conversation (e.g. during `/reportgen` create flow), the FSM state is lost and the admin must restart the flow. For production, swap `MemoryStorage` for `MongoStorage` (aiogram-contrib). |
