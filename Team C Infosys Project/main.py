from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn, os, sqlite3, hashlib, time, json

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "chat.db")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── In-memory state ───────────────────────────────────────────────────────────
active_connections: dict[WebSocket, dict] = {}
rate_tracker:       dict[str, list]       = {}   # username → [timestamps]
seen_ids:           set                   = set()

RATE_LIMIT       = 10           # messages
RATE_WINDOW      = 10           # seconds
MAX_BASE64_BYTES = 5_242_880    # 5 MB

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            created_at   REAL DEFAULT (unixepoch())
        );
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            msgid     TEXT UNIQUE NOT NULL,
            room      TEXT NOT NULL,
            username  TEXT NOT NULL,
            type      TEXT NOT NULL,
            content   TEXT NOT NULL,
            timestamp REAL NOT NULL,
            edited    INTEGER DEFAULT 0,
            reply_to  TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS reactions (
            msgid    TEXT NOT NULL,
            username TEXT NOT NULL,
            emoji    TEXT NOT NULL,
            PRIMARY KEY (msgid, username)
        );
        CREATE TABLE IF NOT EXISTS pinned (
            room      TEXT PRIMARY KEY,
            msgid     TEXT,
            content   TEXT,
            pinned_by TEXT
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ── Utilities ─────────────────────────────────────────────────────────────────
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def allowed_rate(username: str) -> bool:
    now = time.time()
    ts  = [t for t in rate_tracker.get(username, []) if now - t < RATE_WINDOW]
    if len(ts) >= RATE_LIMIT:
        rate_tracker[username] = ts
        return False
    ts.append(now)
    rate_tracker[username] = ts
    return True

def get_reactions(msgid: str) -> dict:
    conn = get_db()
    rows = conn.execute(
        "SELECT emoji, COUNT(*) cnt FROM reactions WHERE msgid=? GROUP BY emoji", (msgid,)
    ).fetchall()
    conn.close()
    return {r["emoji"]: r["cnt"] for r in rows}

def save_message(msgid, room, username, mtype, content, ts, reply_to=None):
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO messages "
            "(msgid,room,username,type,content,timestamp,reply_to) VALUES (?,?,?,?,?,?,?)",
            (msgid, room, username, mtype, content, ts, reply_to)
        )
        conn.commit()
    except Exception:
        pass
    conn.close()

def get_history(room: str, limit: int = 60) -> list:
    conn  = get_db()
    rows  = conn.execute(
        "SELECT * FROM messages WHERE room=? ORDER BY timestamp DESC LIMIT ?", (room, limit)
    ).fetchall()
    conn.close()
    result = []
    for r in reversed(rows):
        entry = {
            "type": r["type"], "username": r["username"],
            "msgId": r["msgid"], "timestamp": r["timestamp"],
            "edited": bool(r["edited"]), "reply_to": r["reply_to"],
            "reactions": get_reactions(r["msgid"]),
        }
        if r["type"] == "chat":
            entry["message"] = r["content"]
        else:
            entry["url"] = r["content"]
        result.append(entry)
    return result

def get_pinned(room: str):
    conn = get_db()
    row  = conn.execute("SELECT * FROM pinned WHERE room=?", (room,)).fetchone()
    conn.close()
    return dict(row) if row else None

def room_users(room: str) -> list:
    return [v["username"] for v in active_connections.values() if v.get("room") == room]

async def broadcast(room: str, data: dict):
    for ws, info in list(active_connections.items()):
        if info.get("room") == room:
            try:
                await ws.send_json(data)
            except Exception:
                active_connections.pop(ws, None)

# ── HTTP endpoints ────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

@app.post("/api/auth")
async def auth(request: Request):
    body     = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username:
        return JSONResponse({"ok": False, "error": "Username required"}, 400)

    conn = get_db()
    row  = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    if row:
        if row["password_hash"]:
            if not password:
                conn.close()
                return JSONResponse({"ok": False, "error": "Password required for this account"}, 401)
            if hash_pw(password) != row["password_hash"]:
                conn.close()
                return JSONResponse({"ok": False, "error": "Incorrect password"}, 401)
    else:
        pw_hash = hash_pw(password) if password else None
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?,?)", (username, pw_hash))
        conn.commit()

    conn.close()
    return JSONResponse({"ok": True, "username": username})

@app.get("/api/rooms")
async def api_rooms():
    rooms = list({v["room"] for v in active_connections.values()})
    return JSONResponse({"rooms": rooms})

@app.get("/api/users/{room}")
async def api_users(room: str):
    return JSONResponse({"users": room_users(room)})

@app.post("/api/forward")
async def api_forward(request: Request):
    body     = await request.json()
    username = body.get("username", "")
    target   = body.get("room", "")
    message  = body.get("message", "")
    if not (username and target and message):
        return JSONResponse({"ok": False}, 400)
    msgid = f"fwd-{time.time()}-{username}"
    ts    = time.time()
    save_message(msgid, target, username, "chat", f"↪ {message}", ts)
    await broadcast(target, {
        "type": "chat", "username": username,
        "message": f"↪ {message}", "msgId": msgid, "timestamp": ts,
    })
    return JSONResponse({"ok": True})

# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/{username}/{room}")
async def ws_endpoint(websocket: WebSocket, username: str, room: str):
    await websocket.accept()
    active_connections[websocket] = {"username": username, "room": room}

    # Deliver history + pinned + user list on connect
    await websocket.send_json({"type": "history", "messages": get_history(room)})
    pinned = get_pinned(room)
    if pinned:
        await websocket.send_json({"type": "pinned_update", "pinned": pinned})
    await broadcast(room, {"type": "users_update", "users": room_users(room)})
    await broadcast(room, {"type": "system", "message": f"{username} joined 🛡️"})

    try:
        while True:
            data     = await websocket.receive_json()
            mtype    = data.get("type", "")
            content_types = {"chat", "image", "voice"}

            # ── Rate limit
            if mtype in content_types:
                if not allowed_rate(username):
                    await websocket.send_json({
                        "type": "error",
                        "message": "⚠️ Slow down! Max 10 messages per 10 seconds."
                    })
                    continue

            # ── File size guard
            if mtype in ("image", "voice"):
                if len((data.get("url") or "").encode()) > MAX_BASE64_BYTES:
                    await websocket.send_json({
                        "type": "error", "message": "❌ File too large (max 5 MB)."
                    })
                    continue

            # ── Deduplication
            if mtype in content_types:
                mid = data.get("msgId")
                if mid:
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)

            # ── Dispatch
            if mtype == "chat":
                mid      = data.get("msgId", f"m-{time.time()}")
                ts       = time.time()
                reply_to = data.get("reply_to")
                save_message(mid, room, username, "chat", data.get("message", ""), ts, reply_to)
                await broadcast(room, {
                    "type": "chat", "username": username,
                    "message": data.get("message", ""), "msgId": mid,
                    "timestamp": ts, "reply_to": reply_to,
                })

            elif mtype in ("image", "voice"):
                mid = data.get("msgId", f"m-{time.time()}")
                ts  = time.time()
                save_message(mid, room, username, mtype, data.get("url", ""), ts)
                await broadcast(room, {
                    "type": mtype, "username": username,
                    "url": data.get("url", ""), "msgId": mid, "timestamp": ts,
                })

            elif mtype == "delete_msg":
                mid = data.get("msgId")
                if mid:
                    conn = get_db()
                    conn.execute("DELETE FROM messages WHERE msgid=? AND username=?", (mid, username))
                    conn.execute("DELETE FROM reactions WHERE msgid=?", (mid,))
                    conn.commit(); conn.close()
                    await broadcast(room, {"type": "delete_msg", "msgId": mid})

            elif mtype == "edit_msg":
                mid      = data.get("msgId")
                new_text = data.get("message", "")
                if mid:
                    conn = get_db()
                    conn.execute(
                        "UPDATE messages SET content=?, edited=1 "
                        "WHERE msgid=? AND username=? AND type='chat'",
                        (new_text, mid, username)
                    )
                    conn.commit(); conn.close()
                    await broadcast(room, {
                        "type": "edit_msg", "msgId": mid,
                        "message": new_text, "username": username,
                    })

            elif mtype == "react_msg":
                mid   = data.get("msgId")
                emoji = data.get("emoji", "")
                if mid and emoji:
                    conn     = get_db()
                    existing = conn.execute(
                        "SELECT emoji FROM reactions WHERE msgid=? AND username=?", (mid, username)
                    ).fetchone()
                    if existing:
                        if existing["emoji"] == emoji:
                            conn.execute("DELETE FROM reactions WHERE msgid=? AND username=?", (mid, username))
                        else:
                            conn.execute("UPDATE reactions SET emoji=? WHERE msgid=? AND username=?", (emoji, mid, username))
                    else:
                        conn.execute("INSERT INTO reactions (msgid,username,emoji) VALUES (?,?,?)", (mid, username, emoji))
                    conn.commit()
                    reactions = {r["emoji"]: r["cnt"] for r in conn.execute(
                        "SELECT emoji, COUNT(*) cnt FROM reactions WHERE msgid=? GROUP BY emoji", (mid,)
                    ).fetchall()}
                    conn.close()
                    await broadcast(room, {"type": "reaction_update", "msgId": mid, "reactions": reactions})

            elif mtype == "pin_msg":
                mid     = data.get("msgId")
                content = data.get("content", "")
                if mid:
                    conn = get_db()
                    conn.execute(
                        "INSERT OR REPLACE INTO pinned (room,msgid,content,pinned_by) VALUES (?,?,?,?)",
                        (room, mid, content, username)
                    )
                    conn.commit(); conn.close()
                    await broadcast(room, {
                        "type": "pinned_update",
                        "pinned": {"room": room, "msgid": mid, "content": content, "pinned_by": username},
                    })

            elif mtype == "unpin_msg":
                conn = get_db()
                conn.execute("DELETE FROM pinned WHERE room=?", (room,))
                conn.commit(); conn.close()
                await broadcast(room, {"type": "pinned_update", "pinned": None})

            elif mtype == "read_receipt":
                await broadcast(room, {
                    "type": "read_receipt",
                    "msgId": data.get("msgId"),
                    "username": username,
                })

            elif mtype in ("typing", "stop_typing"):
                await broadcast(room, {**data, "username": username})

            else:
                await broadcast(room, {**data, "username": username})

    except WebSocketDisconnect:
        active_connections.pop(websocket, None)
        await broadcast(room, {"type": "users_update", "users": room_users(room)})
        await broadcast(room, {"type": "system", "message": f"{username} left ❌"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
