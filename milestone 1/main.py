import socketio
from fastapi import FastAPI
import uvicorn


sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*"
)


fastapi_app = FastAPI()


app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)


@sio.event
async def connect(sid, environ):
    print("Client connected:", sid)


@sio.event
async def disconnect(sid):
    print("Client disconnected:", sid)


@sio.on("chat_message")
async def handle_message(sid, data):
    print("Message received:", data)
    await sio.emit("chat_message", data)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)