from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

connections = {}
usernames   = {}

@app.get("/")
async def home():
    with open("M2_index.html", "r") as f:
        return HTMLResponse(f.read())

async def broadcast(data):
    for connection in connections:
        await connection.send_json(data)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    try:
        data     = await ws.receive_json()
        username = data.get("username", "Anonymous")

        connections[ws] = ws
        usernames[ws]   = username

        await broadcast({"type": "system", "message": f"{username} joined the chat 👋"})

        while True:
            data    = await ws.receive_json()
            message = data.get("message", "")

            if message.strip() == "":
                continue

            await broadcast({"type": "chat", "user": username, "message": message})

    except WebSocketDisconnect:
        connections.pop(ws, None)
        left_user = usernames.pop(ws, "Someone")
        await broadcast({"type": "system", "message": f"{left_user} left the chat ❌"})

if __name__ == "__main__":
    uvicorn.run("M2_main:app", host="localhost", port=8000, reload=True)
