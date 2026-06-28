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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import get_settings

router = APIRouter(tags=["voice"], prefix="/voice")

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
