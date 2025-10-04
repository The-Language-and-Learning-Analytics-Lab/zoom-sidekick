import requests
import os
import base64
from dotenv import load_dotenv
import time


class RecallAI:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        region = os.getenv("RECALL_REGION", "us-west-2").strip()
        self.base_url = f"https://{region}.recall.ai/api/v1/bot/"
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Token {os.getenv('RECALL_API_KEY')}",
        }
        self.id = None

    @staticmethod
    def get_silent_mp3_b64():
        """
        Return a short silent MP3 as base64. Set RECALL_SILENT_MP3_B64 in your env.
        Required by Recall to enable the Output Audio endpoint even if you don't
        actually want automatic playback. See docs: Output Audio.
        """
        b64 = os.getenv("RECALL_SILENT_MP3_B64", "").strip()
        if not b64:
            print(
                "[RecallAI] Warning: RECALL_SILENT_MP3_B64 is not set. "
                "automatic_audio_output will use an empty placeholder which may be rejected."
            )
        return b64

    def create(self, meeting_url, bot_name="Neil"):
        # Create a bot and join it to a meeting
        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            # Required to later call POST /bot/{id}/output_audio/
            "automatic_audio_output": {
                "in_call_recording": {
                    "data": {
                        "kind": "mp3",
                        "b64_data": self.get_silent_mp3_b64(),
                    }
                }
            },
            "recording_config": {
                # Enable mixed raw audio generation (16 kHz mono, S16LE)
                "audio_mixed_raw": {},
                # Register a realtime WebSocket endpoint to receive audio packets
                "realtime_endpoints": [
                    {
                        "type": "websocket",
                        "url": f"wss://{os.getenv('WEBHOOK_URL').split('//')[1]}/audio",
                        "events": ["audio_mixed_raw.data"],
                    }
                ],
            },
        }

        response = requests.post(self.base_url, headers=self.headers, json=payload)
        response.raise_for_status()
        data = response.json()
        self.id = data.get("id")
        if not self.id:
            raise RuntimeError(f"Failed to create bot: {data}")
        return self.id

    def retrieve(self):
        # Retrieve information about the bot
        url = self.base_url + self.id
        response = requests.get(url, headers=self.headers)
        return response.json()

    def get_meeting_participants(self):
        # Get the list of participants in the meeting
        bot_response = self.retrieve()
        return bot_response["meeting_participants"]

    def send_chat_message(self, message, to_speaker=None):
        # Send a chat message in the meeting
        url = self.base_url + self.id + "/send_chat_message"
        payload = {"message": message}
        if to_speaker:
            payload["to"] = to_speaker
        response = requests.post(url, headers=self.headers, json=payload)
        return response.json()

    def output_audio(self, base64_audio):
        # Output audio in the meeting
        url = self.base_url + self.id + "/output_audio/"
        payload = {"b64_data": base64_audio, "kind": "mp3"}
        print(f"Sending request to {url}")
        print(f"Payload size: {len(str(payload))} characters")

        # Check if payload exceeds maximum allowed length
        if len(payload["b64_data"]) > 1835008:
            print(
                f"Warning: b64_data exceeds maximum allowed length of 1835008 characters"
            )
            print(f"Payload size: {len(payload['b64_data'])} characters")
            payload["b64_data"] = payload["b64_data"][:1000000]

        try:
            start = time.time()
            response = requests.post(url, headers=self.headers, json=payload)
            end = time.time()
            print(f"Time taken to output audio: {end - start} seconds")
            print(f"Response status code: {response.status_code}")
            print(f"Response content: {response.text}")
            response.raise_for_status()  # Raise an exception for bad status codes
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error outputting audio: {e}")
            print(
                f"Response content: {response.text if 'response' in locals() else 'No response'}"
            )
            return None

    def stop_audio(self):
        # Stop audio output
        url = self.base_url + self.id + "/output_audio/"
        response = requests.delete(url, headers=self.headers)
        return response.text, response.status_code

    def remove(self):
        # Remove the bot from the call
        url = self.base_url + self.id + "/leave_call/"
        response = requests.post(url, headers=self.headers)
        return response.json()
