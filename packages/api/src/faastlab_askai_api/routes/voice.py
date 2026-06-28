"""Voice — OpenAI Whisper STT + OpenAI TTS for the chat mic button.

Two small endpoints behind the chat page's mic + read-aloud:
  POST /v1/voice/transcribe  (multipart audio) -> {text}       (Whisper)
  POST /v1/voice/speak       ({text})           -> audio/mpeg   (OpenAI TTS)

Both use the server OPENAI_API_KEY against api.openai.com — audio is OpenAI-only
(no sovereign/Qwen routing, no GPU). Auth-gated so anonymous callers can't spend
tokens. The transcribed text is fed back through the normal /ask RAG flow by the
frontend, so spoken questions stay grounded in the corpus with citations.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_askai.prompts import RAG_SYSTEM_PROMPT, role_prompt_name
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.gateway import PromptRegistry

router = APIRouter(tags=["voice"], prefix="/voice")

# The function the realtime model calls to ground its spoken answers. The
# BROWSER executes it (against /v1/search) and feeds the passages back, so the
# voice answer comes from the corpus, not the model's own memory.
_SEARCH_TOOL = {
    "type": "function",
    "name": "search_documents",
    "description": (
        "Search the company's document corpus for passages relevant to the "
        "user's question. ALWAYS call this before answering anything that needs "
        "document knowledge; answer only from what it returns."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."}
        },
        "required": ["query"],
    },
}

# OpenAI's own audio upload limit is 25 MB; a spoken question is far smaller.
_MAX_AUDIO_BYTES = 25 * 1024 * 1024


def _client() -> AsyncOpenAI:
    """OpenAI client pinned to api.openai.com (NOT llm_base_url — a sovereign
    Qwen endpoint has no audio routes). Uses the server key, never BYOK."""
    key = get_settings().openai_api_key
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Voice needs OPENAI_API_KEY configured on the server.",
        )
    return AsyncOpenAI(api_key=key)


class TranscriptionOut(BaseModel):
    text: str


@router.post("/transcribe", response_model=TranscriptionOut)
async def transcribe(
    file: UploadFile = File(...),
    _principal: Principal = Depends(get_principal),
) -> TranscriptionOut:
    """Speech -> text via OpenAI Whisper."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty audio")
    if len(data) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (max 25 MB)")
    s = get_settings()
    try:
        result = await _client().audio.transcriptions.create(
            model=s.stt_model,
            file=(
                file.filename or "audio.webm",
                data,
                file.content_type or "audio/webm",
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"transcription failed: {exc}") from exc
    return TranscriptionOut(text=(result.text or "").strip())


class RealtimeSessionIn(BaseModel):
    role: str | None = None  # role slug → drives the voice persona's instructions
    voice: str | None = None  # override the realtime voice


async def _role_instructions(role: str | None) -> str:
    """Build the realtime session's system instructions: the selected role's
    prompt + a self-introduction + grounding/turn-taking guidance for voice."""
    reg = PromptRegistry()
    base: str | None = None
    for name in ([role_prompt_name(role)] if role else []) + ["rag.system"]:
        try:
            base = (await reg.get(name)).template
            break
        except Exception:
            continue
    base = base or RAG_SYSTEM_PROMPT
    return (
        base
        + "\n\n--- Voice conversation ---\n"
        "You are speaking out loud in a live, two-way voice conversation. "
        "Open by briefly introducing who you are and what you help with (one "
        "sentence). For anything needing document knowledge, CALL the "
        "search_documents tool first and answer ONLY from its results, naming "
        "the source titles. Keep replies short, natural and conversational."
    )


@router.post("/realtime-session")
async def realtime_session(
    body: RealtimeSessionIn,
    _principal: Principal = Depends(get_principal),
) -> dict:
    """Mint a SHORT-LIVED OpenAI Realtime ephemeral token for the browser's
    WebRTC handshake. The server key never reaches the client. Configures the
    role persona, server-VAD turn-taking, and the search_documents tool."""
    s = get_settings()
    if not s.openai_api_key:
        raise HTTPException(
            status_code=503, detail="Voice needs OPENAI_API_KEY on the server."
        )
    payload = {
        "model": s.realtime_model,
        "voice": body.voice or s.realtime_voice,
        "modalities": ["audio", "text"],
        "instructions": await _role_instructions(body.role),
        "input_audio_transcription": {"model": "whisper-1"},
        "turn_detection": {"type": "server_vad"},  # hands-free, auto turn-taking
        "tools": [_SEARCH_TOOL],
        "tool_choice": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            r = await http.post(
                "https://api.openai.com/v1/realtime/sessions",
                headers={
                    "Authorization": f"Bearer {s.openai_api_key}",
                    "Content-Type": "application/json",
                    "OpenAI-Beta": "realtime=v1",
                },
                json=payload,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"realtime session failed: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"realtime session error: {r.text[:300]}")
    return r.json()


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None  # override the deployment's default TTS voice


@router.post("/speak")
async def speak(
    body: SpeakIn,
    _principal: Principal = Depends(get_principal),
) -> Response:
    """Text -> spoken MP3 via OpenAI TTS."""
    s = get_settings()
    try:
        # Streaming-response API is the non-deprecated way to get the bytes.
        async with _client().audio.speech.with_streaming_response.create(
            model=s.tts_model,
            voice=body.voice or s.tts_voice,
            input=body.text,
            response_format="mp3",
        ) as resp:
            content = await resp.read()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"speech failed: {exc}") from exc
    return Response(content=content, media_type="audio/mpeg")
