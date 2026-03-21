from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

@app.get("/")
async def home():
    with open("M1_index.html", "r") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    while True:
        try:
            message = await websocket.receive_text()
            await websocket.send_text(f"Server received: {message}")
        except Exception:
            break

if __name__ == "__main__":
    uvicorn.run("M1_main:app", host="localhost", port=8000, reload=True)
