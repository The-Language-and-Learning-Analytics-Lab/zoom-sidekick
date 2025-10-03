import json
import os
import aiohttp

url = "wss://api.openai.com/v1/realtime?model=gpt-realtime"


class OpenAIRealtime:
    def __init__(self):
        # Initialize the WebSocket connection as None
        self.ws = None
        self.url = url
        self.headers = {
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "OpenAI-Beta": "realtime=v1",
        }
        self.session = None

    def on_open(self, ws):
        print("Connected to server.")

    def on_message(self, ws, message):
        data = json.loads(message)
        print("Received event:", json.dumps(data, indent=2))

    async def connect(self):
        print(f"Connecting to OpenAI Realtime API at {self.url}")
        self.session = aiohttp.ClientSession(headers=self.headers)
        self.ws = await self.session.ws_connect(self.url)
        await self.update_session()

    async def update_session(self):
        # Check if the WebSocket connection is open
        if self.ws and not self.ws.closed:
            # Define the instructions for the AI's behavior during the session
            instructions = """
                You are a helpful sales assistant that listens to a sales call and responds when it's appropriate.
                The goal of the call may vary, it may be an intro call, it may be a call to discuss testing feedback, it may be to discuss pricing, etc.

                You will provide suggestions to help the sales agent on the call.
                You will only respond when the sales agent says "Hey Bot, can you help me?" Otherwise, you will remain silent.
                Only speak in English.
            """

            # Send session update with modalities, instructions, and other settings
            await self.ws.send_str(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "modalities": [
                                "audio",
                                "text",
                            ],  # Specify modalities for the session
                            "instructions": instructions,  # Provide the AI with specific instructions
                            "output_audio_format": "mp3",  # Set the output audio format
                            "turn_detection": {  # Configure turn detection settings
                                "type": "server_vad",
                                "threshold": 0.3,
                                "prefix_padding_ms": 100,
                                "silence_duration_ms": 100,
                            },
                            "voice": "nova",  # Specify the voice to be used
                            "input_audio_transcription": {"enabled": True},
                        },
                    }
                )
            )

    async def send_audio(self, audio_data):
        # Send audio data to the WebSocket if the connection is open
        if self.ws and not self.ws.closed:
            try:
                await self.ws.send_str(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": audio_data,  # Append audio data to the input buffer
                        }
                    )
                )
            except Exception as e:
                print(f"Error sending audio: {e}")  # Handle WebSocket exceptions

    async def send_response_create(self):
        # Request the creation of a response from the AI
        if self.ws and not self.ws.closed:
            try:
                await self.ws.send_str(json.dumps({"type": "response.create"}))
            except Exception as e:
                print(
                    f"Error sending response create: {e}"
                )  # Handle WebSocket exceptions

    async def receive_messages(self, message_handler=None):
        while True:
            try:
                msg = await self.ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        parsed_message = json.loads(msg.data)
                    except Exception:
                        # Non-JSON text frames aren't expected; skip
                        continue
                    if message_handler:
                        await message_handler(parsed_message)
                    else:
                        print(parsed_message)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    # Realtime may send binary chunks; ignore for now
                    continue
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    print("Connection to OpenAI realtime WebSocket closed")
                    break
            except Exception as e:
                print(f"WebSocket receive error: {e}")
                break

    async def close(self):
        try:
            if self.ws and not self.ws.closed:
                await self.ws.close()
        finally:
            if self.session:
                await self.session.close()
