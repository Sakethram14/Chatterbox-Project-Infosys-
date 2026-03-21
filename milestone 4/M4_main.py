from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

active_connections = []
usernames          = {}
rooms              = {}

@app.get("/")
async def home():
    with open("M4_index.html", "r") as f:
        return HTMLResponse(f.read())

async def broadcast(room, data):
    for connection in active_connections:
        if rooms.get(connection) == room:
            await connection.send_json(data)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    try:
        data     = await ws.receive_json()
        username = data.get("username", "Anonymous")
        room     = data.get("room", "general")

        active_connections.append(ws)
        usernames[ws] = username
        rooms[ws]     = room

        await broadcast(room, {"type": "system", "message": f"{username} joined {room} 👋"})

        while True:
            data = await ws.receive_json()

            if data["type"] == "chat":
                if data["message"].strip() == "":
                    continue
                await broadcast(rooms[ws], {"type": "chat", "username": username, "message": data["message"]})

            elif data["type"] == "switch_room":
                old_room = rooms[ws]
                new_room = data.get("room", "general")

                if old_room == new_room:
                    continue

                await broadcast(old_room, {"type": "system", "message": f"{username} left {old_room} ❌"})
                rooms[ws] = new_room
                await broadcast(new_room, {"type": "system", "message": f"{username} joined {new_room} 👋"})

            elif data["type"] == "typing":
                await broadcast(rooms[ws], {"type": "typing", "username": username})

            elif data["type"] == "stop_typing":
                await broadcast(rooms[ws], {"type": "stop_typing"})

    except WebSocketDisconnect:
        left_user = usernames.get(ws, "Someone")
        room      = rooms.get(ws)

        if ws in active_connections:
            active_connections.remove(ws)

        usernames.pop(ws, None)
        rooms.pop(ws, None)

        if room:
            await broadcast(room, {"type": "system", "message": f"{left_user} left {room} ❌"})

if __name__ == "__main__":
    uvicorn.run("M4_main:app", host="localhost", port=8000, reload=True)
