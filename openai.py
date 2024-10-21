import json
import os
import websockets

# WebSocket URL for connecting to OpenAI's realtime API
url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"

class OpenAIRealtime:
    def __init__(self):
        # Initialize the WebSocket connection as None
        self.ws = None

    async def connect(self):
        # Establish a WebSocket connection with the necessary headers
        self.ws = await websockets.connect(
            url,
            extra_headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",  # Use API key from environment variables
                "OpenAI-Beta": "realtime=v1",  # Specify the beta version for realtime
            }
        )
        # Update the session with specific instructions and settings
        await self.update_session()

    async def update_session(self):
        # Check if the WebSocket connection is open
        if self.ws and self.ws.open:
            # Define the instructions for the AI's behavior during the session
            instructions = '''
                You are a helpful sales assistant that listens to a sales call and responds when it's appropriate.
                The goal of the call may vary, it may be an intro call, it may be a call to discuss testing feedback, it may be to discuss pricing, etc.

                You will provide suggestions to help the sales agent on the call.
                You will only respond when the sales agent says "Hey Bot, can you help me?" Otherwise, you will remain silent.
                Only speak in English.
            '''

            # Send session update with modalities, instructions, and other settings
            await self.ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["audio", "text"],  # Specify modalities for the session
                    "instructions": instructions,  # Provide the AI with specific instructions
                    "output_audio_format": "mp3",  # Set the output audio format
                    "turn_detection": {  # Configure turn detection settings
                        "type": "server_vad",
                        "threshold": 0.3,
                        "prefix_padding_ms": 100,
                        "silence_duration_ms": 100
                    },
                    "voice": "nova"  # Specify the voice to be used
                }
            }))

    async def send_audio(self, audio_data):
        # Send audio data to the WebSocket if the connection is open
        if self.ws and self.ws.open:
            try:
                await self.ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": audio_data  # Append audio data to the input buffer
                }))
            except websockets.exceptions.WebSocketException as e:
                print(f"Error sending audio: {e}")  # Handle WebSocket exceptions

    async def send_response_create(self):
        # Request the creation of a response from the AI
        if self.ws and self.ws.open:
            try:
                await self.ws.send(json.dumps({"type": "response.create"}))
            except websockets.exceptions.WebSocketException as e:
                print(f"Error sending response create: {e}")  # Handle WebSocket exceptions

    async def receive_messages(self, message_handler=None):
        # Continuously receive messages from the WebSocket
        while True:
            try:
                message = await self.ws.recv()  # Receive a message
                parsed_message = json.loads(message)  # Parse the JSON message
                
                if message_handler:
                    await message_handler(parsed_message)  # Handle the message with a custom handler if provided
                else:
                    print(parsed_message)  # Print the message if no handler is provided
            except websockets.exceptions.ConnectionClosed:
                print("Connection to OpenAI realtime WebSocket closed")  # Handle closed connection
                break
