
from fastapi import FastAPI, WebSocket
import uvicorn


app = FastAPI()


@app.get("/")
async def home():
    return {"message": "WebSocket Server is running"}



@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

   
    await websocket.accept()
    print("Client connected")

    while True:
        try:
            
            data = await websocket.receive_text()
            print("Received:", data)

        
            response = "Server received: " + data
            await websocket.send_text(response)

        except Exception:
            print("Client disconnected")
            break



if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
