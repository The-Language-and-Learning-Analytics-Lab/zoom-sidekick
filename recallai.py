import requests
import os
import base64
from dotenv import load_dotenv
import time


class RecallAI:
    def __init__(self):
        # Load environment variables
        load_dotenv()

        # Validate required environment variables
        recall_api_key = os.getenv("RECALL_API_KEY")
        if not recall_api_key:
            raise ValueError("RECALL_API_KEY environment variable is not set")

        # WEBHOOK_URL will be set later when the app starts
        self.base_url = "https://us-west-2.recall.ai/api/v1/bot/"
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"{recall_api_key}",
        }
        self.id = None

    def create(self, meeting_url, bot_name="Neil"):
        # Create a bot and join it to a meeting
        webhook_url = os.getenv("WEBHOOK_URL")
        if not webhook_url:
            raise ValueError("WEBHOOK_URL environment variable is not set")
        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "recording_config": {
                "realtime_endpoints": [
                    {
                        "type": "websocket",
                        "url": f'wss://{webhook_url.split("//")[1]}/audio',
                        "events": ["audio_mixed_raw.data"],
                    }
                ]
            },
            "automatic_audio_output": {
                "in_call_recording": {
                    "data": {"kind": "mp3", "b64_data": self.generate_silence()}
                }
            },
        }

        print(f"Creating bot with payload: {payload}")
        print(f"API URL: {self.base_url}")
        print(f"Headers: {self.headers}")

        response = requests.post(self.base_url, headers=self.headers, json=payload)

        print(f"Response status code: {response.status_code}")
        print(f"Response headers: {response.headers}")
        print(f"Response content: {response.text}")

        if response.status_code != 200:
            raise Exception(
                f"API request failed with status "
                f"{response.status_code}: {response.text}"
            )

        response_data = response.json()
        print(f"Response data: {response_data}")

        # Check if 'id' field exists in the response
        if "id" not in response_data:
            print(
                f"Warning: 'id' field not found in response. "
                f"Available fields: {list(response_data.keys())}"
            )
            # Try alternative field names that might contain the bot ID
            if "bot_id" in response_data:
                self.id = response_data["bot_id"]
            elif (
                "bot" in response_data
                and isinstance(response_data["bot"], dict)
                and "id" in response_data["bot"]
            ):
                self.id = response_data["bot"]["id"]
            else:
                available_fields = list(response_data.keys())
                raise KeyError(
                    f"'id' field not found in response. "
                    f"Available fields: {available_fields}"
                )
        else:
            self.id = response_data["id"]

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
        url = self.base_url + self.id + "/output_audio"
        payload = {"b64_data": base64_audio, "kind": "mp3"}
        print(f"Sending request to {url}")
        print(f"Payload size: {len(str(payload))} characters")

        # Check if payload exceeds maximum allowed length
        if len(payload["b64_data"]) > 1835008:
            print(
                "Warning: b64_data exceeds maximum allowed length of "
                "1835008 characters"
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
            # Raise an exception for bad status codes
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error outputting audio: {e}")
            response_text = response.text if "response" in locals() else "No response"
            print(f"Response content: {response_text}")
            return None

    def stop_audio(self):
        # Stop audio output
        url = self.base_url + self.id + "/output_audio"
        response = requests.delete(url, headers=self.headers)
        return response.text, response.status_code

    def remove(self):
        # Remove the bot from the call
        url = self.base_url + self.id + "/leave_call"
        response = requests.post(url, headers=self.headers)
        return response.json()
