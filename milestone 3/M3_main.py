from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

connections = {}
usernames   = {}
rooms       = {}

@app.get("/")
async def home():
    with open("M3_index.html", "r") as f:
        return HTMLResponse(f.read())

async def broadcast(room, data):
    for conn in connections:
        if rooms.get(conn) == room:
            await conn.send_json(data)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    try:
        data     = await ws.receive_json()
        username = data.get("username", "Anonymous")
        room     = data.get("room", "general")

        connections[ws] = ws
        usernames[ws]   = username
        rooms[ws]       = room

        await broadcast(room, {"type": "system", "message": f"{username} joined {room} 👋"})

        while True:
            data = await ws.receive_json()

            if data["type"] == "chat":
                if data["message"].strip() == "":
                    continue
                await broadcast(room, {"type": "chat", "username": username, "message": data["message"]})

            elif data["type"] == "typing":
                await broadcast(room, {"type": "typing", "username": username})

            elif data["type"] == "stop_typing":
                await broadcast(room, {"type": "stop_typing"})

    except WebSocketDisconnect:
        left_user = usernames.get(ws, "Someone")
        room      = rooms.get(ws)

        connections.pop(ws, None)
        usernames.pop(ws, None)
        rooms.pop(ws, None)

        if room:
            await broadcast(room, {"type": "system", "message": f"{left_user} left {room} ❌"})

if __name__ == "__main__":
    uvicorn.run("M3_main:app", host="localhost", port=8000, reload=True)
