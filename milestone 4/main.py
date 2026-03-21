from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

# -----------------------------
# Data Structures
# -----------------------------
active_connections = []
usernames = {}
rooms = {}

# -----------------------------
# Broadcast Function
# -----------------------------
async def broadcast(room, data):
    for connection in active_connections:
        if rooms.get(connection) == room:
            await connection.send_json(data)

# -----------------------------
# WebSocket Endpoint
# -----------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):

    await ws.accept()

    try:
        data = await ws.receive_json()

        username = data.get("username", "Anonymous")
        room = data.get("room", "general")

        active_connections.append(ws)
        usernames[ws] = username
        rooms[ws] = room

        # Join notification
        await broadcast(room,{
            "type":"system",
            "message":f"{username} joined {room} 👋"
        })

        while True:

            data = await ws.receive_json()

            # -----------------------------
            # Chat Message
            # -----------------------------
            if data["type"] == "chat":

                msg = data.get("message","")

                if msg.strip() == "":
                    continue

                await broadcast(room,{
                    "type":"chat",
                    "username":username,
                    "message":msg
                })

            # -----------------------------
            # Typing Indicator
            # -----------------------------
            if data["type"] == "typing":

                await broadcast(room,{
                    "type":"typing",
                    "username":username
                })

            # -----------------------------
            # Stop Typing
            # -----------------------------
            if data["type"] == "stop_typing":

                await broadcast(room,{
                    "type":"stop_typing"
                })

    except WebSocketDisconnect:

        left_user = usernames.get(ws,"Someone")
        room = rooms.get(ws)

        if ws in active_connections:
            active_connections.remove(ws)

        usernames.pop(ws,None)
        rooms.pop(ws,None)

        # Leave notification
        await broadcast(room,{
            "type":"system",
            "message":f"{left_user} left {room} ❌"
        })


# -----------------------------
# Run Server
# -----------------------------
if __name__ == "__main__":
    uvicorn.run("main:app",host="localhost",port=8000,reload=True)