import socketio
from fastapi import FastAPI
import uvicorn

# Socket.IO server
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# FastAPI app
fastapi_app = FastAPI()

# Combine apps
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

# Store users
users = {}
rooms = {}

# -----------------------------
# User Connect
# -----------------------------
@sio.event
async def connect(sid, environ):
    print("Client connected:", sid)

# -----------------------------
# User Join Room
# -----------------------------
@sio.on("join")
async def join_room(sid, data):

    username = data["username"]
    room = data["room"]

    users[sid] = username
    rooms[sid] = room

    await sio.enter_room(sid, room)

    print(f"{username} joined {room}")

    await sio.emit(
        "system",
        f"{username} joined {room} 👋",
        room=room
    )

# -----------------------------
# Chat Message
# -----------------------------
@sio.on("chat_message")
async def chat_message(sid, data):

    username = users.get(sid)
    room = rooms.get(sid)

    message = data["message"]

    await sio.emit(
        "chat_message",
        {"username": username, "message": message},
        room=room
    )

# -----------------------------
# Typing Indicator
# -----------------------------
@sio.on("typing")
async def typing(sid):

    username = users.get(sid)
    room = rooms.get(sid)

    await sio.emit(
        "typing",
        f"{username} is typing...",
        room=room,
        skip_sid=sid
    )

# -----------------------------
# Stop Typing
# -----------------------------
@sio.on("stop_typing")
async def stop_typing(sid):

    room = rooms.get(sid)

    await sio.emit(
        "stop_typing",
        room=room
    )

# -----------------------------
# Disconnect
# -----------------------------
@sio.event
async def disconnect(sid):

    username = users.get(sid)
    room = rooms.get(sid)

    if room:

        await sio.emit(
            "system",
            f"{username} left {room} ❌",
            room=room
        )

    users.pop(sid, None)
    rooms.pop(sid, None)

    print("Client disconnected")

# -----------------------------
# Run Server
# -----------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)