# requirements:
#   fastapi==0.115.*  uvicorn[standard]==0.30.*  websockets==12.*  httpx==0.27.*
#   python-dotenv==1.*  pydub==0.25.*  ffmpeg must be installed on the system
#
# .env:
#   RECALL_API_KEY=...
#   OPENAI_API_KEY=...
#   ZOOM_MEETING_URL=https://us02web.zoom.us/j/XXXXXXXXXX

import asyncio
import base64
import json
import os
import uuid
from io import BytesIO

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydub import AudioSegment
import websockets

load_dotenv()

RECALL_API_KEY = os.environ["RECALL_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ZOOM_MEETING_URL = os.environ["ZOOM_MEETING_URL"]

# --- OpenAI Realtime client (single connection) --------------------------------


class OpenAIRealtimeClient:
    def __init__(self):
        self.ws = None
        self.lock = asyncio.Lock()
        self.audio_buffer = bytearray()
        self.connected = asyncio.Event()

    async def connect(self):
        # Official websocket endpoint for realtime models (WebSocket mode).
        # Model choices evolve; "gpt-realtime" or "gpt-4o-realtime-preview" are common.
        # See docs for the latest naming.  [oai_citation:3‡Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/realtime-audio-quickstart?utm_source=chatgpt.com)
        url = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
        self.ws = await websockets.connect(
            url, additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
        )
        # Configure the session: pcm16 IO, server VAD, a voice name.
        await self.ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "voice": "alloy",
                        "input_audio_format": "pcm16",
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 200,
                            "create_response": True,
                        },
                    },
                }
            )
        )
        self.connected.set()
        asyncio.create_task(self._reader())

    async def _reader(self):
        try:
            async for msg in self.ws:
                event = json.loads(msg)
                t = event.get("type", "")
                # Realtime WS sends audio frames as base64 "delta" chunks; names vary by release.
                # Commonly seen: "response.audio.delta" / "response.audio.done".  [oai_citation:4‡Medium](https://medium.com/thedeephub/building-a-voice-enabled-python-fastapi-app-using-openais-realtime-api-bfdf2947c3e4?utm_source=chatgpt.com)
                if t == "response.audio.delta":
                    chunk_b64 = event.get("delta", "")
                    if chunk_b64:
                        self.audio_buffer += base64.b64decode(chunk_b64)
                elif t in (
                    "response.audio.done",
                    "response.completed",
                    "response.done",
                ):
                    # Signal to whoever is waiting that an utterance finished.
                    pass
        except Exception:
            self.connected.clear()

    async def push_meeting_audio_pcm16(self, pcm16_b64: str):
        # Stream Recall's meeting audio into OpenAI
        # OpenAI expects base64 audio for inputAudioBuffer.append.  [oai_citation:5‡Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/realtime-audio-reference?utm_source=chatgpt.com)
        if not self.connected.is_set():
            await self.connect()
        await self.ws.send(
            json.dumps({"type": "input_audio_buffer.append", "audio": pcm16_b64})
        )
        # With server_vad enabled, OpenAI decides when to commit and respond.
        # If you disable VAD, you'd also send "input_audio_buffer.commit".

    def consume_and_reset_pcm16(self) -> bytes:
        b = bytes(self.audio_buffer)
        self.audio_buffer = bytearray()
        return b


oai = OpenAIRealtimeClient()

# --- Recall.ai helpers ----------------------------------------------------------

RECALL_BASE = "https://us-west-2.recall.ai/api/v1"
http = httpx.AsyncClient(timeout=30.0)


async def create_recall_bot(realtime_ws_url: str) -> dict:
    """
    Creates a Recall bot that:
      - joins a Zoom meeting,
      - streams raw mixed audio to our WebSocket,
      - and is permitted to play audio back (automatic_audio_output seeded with a short silence).
    """
    # Per docs, realtime_endpoints can include "audio_mixed_raw.data".
    # Output audio endpoint requires bots to be created with automatic_audio_output configured
    # (use a tiny silent MP3 to satisfy the requirement).  [oai_citation:6‡Recall.ai](https://docs.recall.ai/docs/real-time-audio-protocol)
    silent_mp3_b64 = base64.b64encode(
        AudioSegment.silent(duration=300).export(format="mp3").read()
    ).decode()

    payload = {
        "meeting_url": ZOOM_MEETING_URL,
        "recording_config": {
            "audio_mixed_raw": {},
            "realtime_endpoints": [
                {
                    "type": "websocket",
                    "url": realtime_ws_url,
                    "events": ["audio_mixed_raw.data"],
                }
            ],
        },
        "automatic_audio_output": {
            "in_call_recording": {"data": {"kind": "mp3", "b64_data": silent_mp3_b64}}
        },
    }
    r = await http.post(
        f"{RECALL_BASE}/bot/",
        headers={"Authorization": RECALL_API_KEY, "Content-Type": "application/json"},
        json=payload,
    )
    r.raise_for_status()
    return r.json()


async def recall_output_audio(bot_id: str, mp3_b64: str):
    # POST /bot/{id}/output_audio/ with {"kind": "mp3", "b64_data": "..."}  [oai_citation:7‡Recall.ai](https://docs.recall.ai/docs/output-audio-in-meetings)
    r = await http.post(
        f"{RECALL_BASE}/bot/{bot_id}/output_audio/",
        headers={"Authorization": RECALL_API_KEY, "Content-Type": "application/json"},
        json={"kind": "mp3", "b64_data": mp3_b64},
    )
    r.raise_for_status()


# --- FastAPI app & the Recall realtime WebSocket endpoint ----------------------

app = FastAPI()

BOT_ID = None


@app.on_event("startup")
async def startup():
    # Expose /recall as a wss URL publicly (e.g., via Cloud Run/Render + TLS,
    # or use an ngrok tunnel while developing). Use that wss URL in create_recall_bot().
    # See Recall’s docs for local tunneling.  [oai_citation:8‡Recall.ai](https://docs.recall.ai/docs/real-time-audio-protocol)
    asyncio.create_task(oai.connect())


@app.websocket("/recall")
async def recall_ws(ws: WebSocket):
    await ws.accept()
    print("Recall connected")
    try:
        while True:
            raw = await ws.receive_text()
            event = json.loads(raw)
            if event.get("event") == "audio_mixed_raw.data":
                b64_pcm = event["data"]["data"][
                    "buffer"
                ]  # 16kHz mono PCM16 (base64)  [oai_citation:9‡Recall.ai](https://docs.recall.ai/docs/real-time-audio-protocol)
                await oai.push_meeting_audio_pcm16(b64_pcm)

                # Heuristic: occasionally check if OpenAI has finished an utterance.
                # In server_vad mode, the model tends to emit chunks and then finish.
                # Here, every ~500ms we drain and if there's enough, transcode & play.
                if len(oai.audio_buffer) > 48000:  # ~1.5s of 16k PCM16 mono
                    await maybe_speak_back()
            else:
                # ignore other events here, or log them
                pass
    except WebSocketDisconnect:
        print("Recall disconnected")


# --- Turn MP3 playback back into the meeting -----------------------------------


async def maybe_speak_back():
    """If we have accumulated assistant PCM16, flush it, encode to MP3, and send to Zoom via Recall."""
    global BOT_ID
    pcm16 = oai.consume_and_reset_pcm16()
    if not pcm16 or BOT_ID is None:
        return
    # Encode PCM16 -> MP3 (pydub uses ffmpeg under the hood).
    audio = AudioSegment(
        data=pcm16, sample_width=2, frame_rate=16000, channels=1  # 16-bit
    )
    buf = BytesIO()
    audio.export(buf, format="mp3", bitrate="64k")
    mp3_b64 = base64.b64encode(buf.getvalue()).decode()
    await recall_output_audio(BOT_ID, mp3_b64)


# --- Simple one-shot helper to launch a bot against your Zoom URL --------------


@app.get("/spawn-bot")
async def spawn_bot(public_wss: str):
    """
    Hit: http://localhost:8000/spawn-bot?public_wss=wss://your-domain/recall
    Returns bot info; keep the ID handy for debugging in Recall dashboard.
    """
    global BOT_ID
    bot = await create_recall_bot(realtime_ws_url=public_wss)
    BOT_ID = bot["id"]
    return bot
