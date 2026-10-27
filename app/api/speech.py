from __future__ import annotations



import base64
import hashlib
import hmac
import json
import secrets
import logging
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.api.dependencies import get_app_settings, get_current_account, get_repository
from app.core.config import Settings
from app.core.errors import APIError
from app.domain.models import Account
from app.repositories.sql import SQLRepository


router = APIRouter(tags=["speech"])
logger = logging.getLogger("xzxg.speech")


def _as_bool(value: str, fallback: bool = False) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"} if value.strip() else fallback


async def _effective_settings(settings: Settings, repository: SQLRepository) -> Settings:
    values = await repository.config_values()
    update: dict[str, object] = {}
    direct = {
        "tts.provider": "speech_tts_provider", "xunfei.tts.app_id": "xunfei_tts_app_id", "xunfei.tts.api_key": "xunfei_tts_api_key",
        "xunfei.tts.api_secret": "xunfei_tts_api_secret", "xunfei.tts.base_url": "xunfei_tts_base_url", "xunfei.tts.voice": "xunfei_tts_voice",
        "doubao.tts.app_id": "doubao_tts_app_id", "doubao.tts.api_key": "doubao_tts_api_key", "doubao.tts.base_url": "doubao_tts_base_url",
        "doubao.tts.cluster": "doubao_tts_cluster", "doubao.tts.voice": "doubao_tts_voice",
    }
    for key, attr in direct.items():
        if values.get(key, "").strip():
            update[attr] = values[key]
    if "xunfei.tts.enabled" in values:
        update["xunfei_tts_enabled"] = _as_bool(values["xunfei.tts.enabled"])
    if "doubao.tts.enabled" in values:
        update["speech_tts_enabled"] = _as_bool(values["doubao.tts.enabled"])
    if "xunfei.tts.max_runes" in values:
        try:
            update["xunfei_tts_max_runes"] = max(1, min(2000, int(values["xunfei.tts.max_runes"])))
        except ValueError:
            pass
    if "xunfei.tts.timeout_seconds" in values:
        try:
            update["xunfei_tts_timeout_seconds"] = max(1.0, min(60.0, float(values["xunfei.tts.timeout_seconds"])))
        except ValueError:
            pass
    return settings.model_copy(update=update)


def _tts_enabled(settings: Settings) -> bool:
    provider = settings.speech_tts_provider.strip().lower()
    if not (settings.speech_tts_enabled or settings.xunfei_tts_enabled):
        return False
    if provider == "doubao":
        # Credentials are read from environment using pydantic's case-insensitive mapping.
        return bool(getattr(settings, "doubao_tts_app_id", "") and getattr(settings, "doubao_tts_api_key", ""))
    return bool((settings.xunfei_tts_app_id or settings.xunfei_app_id) and (settings.xunfei_tts_api_key or settings.xunfei_api_key) and (settings.xunfei_tts_api_secret or settings.xunfei_api_secret))


def _content_type(settings: Settings) -> str:
    encoding = "mp3" if settings.speech_tts_provider.strip().lower() == "doubao" else settings.xunfei_tts_audio_encoding
    return {"mp3": "audio/mpeg", "lame": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "opus": "audio/ogg"}.get(encoding, "application/octet-stream")


def _tts_url(settings: Settings) -> str:
    base = settings.xunfei_tts_base_url.strip() or "wss://tts-api.xfyun.cn/v2/tts"
    return base


def _xunfei_signed_url(settings: Settings) -> str:
    base = _tts_url(settings)
    parsed = urlparse(base)
    host = parsed.netloc
    path = parsed.path or "/v2/tts"
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    origin = f"host: {host}\n" f"date: {date}\n" f"GET {path} HTTP/1.1"
    api_secret = settings.xunfei_tts_api_secret or settings.xunfei_api_secret
    api_key = settings.xunfei_tts_api_key or settings.xunfei_api_key
    signature = base64.b64encode(hmac.new(api_secret.encode(), origin.encode(), hashlib.sha256).digest()).decode()
    auth_origin = f'api_key="{api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"authorization": base64.b64encode(auth_origin.encode()).decode(), "date": date, "host": host})
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment))


async def _xunfei_tts(settings: Settings, text: str, voice: str) -> bytes:
    try:
        import websockets
    except ImportError as error:  # pragma: no cover - optional runtime dependency
        raise RuntimeError("websockets dependency unavailable") from error
    payload = {
        "common": {"app_id": settings.xunfei_tts_app_id or settings.xunfei_app_id},
        "business": {"aue": settings.xunfei_tts_audio_encoding, "sfl": 1, "vcn": voice or settings.xunfei_tts_voice or settings.speech_tts_voice, "speed": 50, "volume": 50, "pitch": 50, "tte": "UTF8"},
        "data": {"status": 2, "text": base64.b64encode(text.encode()).decode()},
    }
    async with websockets.connect(_xunfei_signed_url(settings), open_timeout=settings.xunfei_tts_timeout_seconds or settings.speech_tts_timeout_seconds, close_timeout=2) as connection:
        await connection.send(json.dumps(payload, ensure_ascii=False))
        chunks: list[bytes] = []
        while True:
            raw = await connection.recv()
            frame = json.loads(raw)
            if int(frame.get("code", 0)) != 0:
                raise RuntimeError(str(frame.get("message") or "xunfei tts error"))
            data = frame.get("data") or {}
            if data.get("audio"):
                chunks.append(base64.b64decode(data["audio"]))
            if int(data.get("status", 0)) == 2:
                break
        audio = b"".join(chunks)
        if not audio:
            raise RuntimeError("xunfei tts returned empty audio")
        return audio


async def _doubao_tts(settings: Settings, text: str, voice: str) -> bytes:
    app_id = getattr(settings, "doubao_tts_app_id", "")
    api_key = getattr(settings, "doubao_tts_api_key", "")
    base_url = getattr(settings, "doubao_tts_base_url", "https://openspeech.bytedance.com/api/v1/tts")
    payload = {
        "app": {"appid": app_id, "token": api_key, "cluster": getattr(settings, "doubao_tts_cluster", "volcano_tts")},
        "user": {"uid": "xzxg-shop"},
        "audio": {"voice_type": voice or getattr(settings, "doubao_tts_voice", "BV700_streaming"), "encoding": "mp3", "speed_ratio": 1.0, "volume_ratio": 1.0, "pitch_ratio": 1.0},
        "request": {"reqid": f"req_{secrets.token_hex(12)}", "text": text, "text_type": "plain", "operation": "query", "with_frontend": 1, "frontend_type": "unitTson"},
    }
    async with httpx.AsyncClient(timeout=settings.speech_tts_timeout_seconds) as client:
        response = await client.post(base_url, json=payload, headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer;{api_key}"})
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"doubao tts http {response.status_code}")
    result = response.json()
    if int(result.get("code", 0)) not in (0, 3000) or not result.get("data"):
        raise RuntimeError(str(result.get("message") or "doubao tts error"))
    return base64.b64decode(result["data"])


@router.get("/speech/tts/config")
async def tts_config(settings: Settings = Depends(get_app_settings), account: Account = Depends(get_current_account), repository: SQLRepository = Depends(get_repository)) -> dict[str, object]:
    del account
    settings = await _effective_settings(settings, repository)
    max_chars = settings.xunfei_tts_max_runes if settings.speech_tts_provider.strip().lower() == "xunfei" else settings.speech_tts_max_text_chars
    return {"enabled": _tts_enabled(settings), "provider": settings.speech_tts_provider.strip().lower() or "xunfei", "voice": settings.xunfei_tts_voice or settings.speech_tts_voice, "max_text_chars": max_chars}


@router.post("/speech/tts")
async def tts(request: dict[str, object], settings: Settings = Depends(get_app_settings), account: Account = Depends(get_current_account), repository: SQLRepository = Depends(get_repository)) -> Response:
    del account
    settings = await _effective_settings(settings, repository)
    if not _tts_enabled(settings):
        raise APIError(501, "tts_not_enabled", "当前后端未配置讯飞语音合成")
    text = str(request.get("text") or "").strip()
    if not text:
        raise APIError(400, "empty_text", "合成文本不能为空")
    max_chars = settings.xunfei_tts_max_runes if settings.speech_tts_provider.strip().lower() == "xunfei" else settings.speech_tts_max_text_chars
    if max_chars > 0 and len(text) > max_chars:
        raise APIError(400, "text_too_long", "合成文本过长")
    voice = str(request.get("voice") or "").strip()
    try:
        if settings.speech_tts_provider.strip().lower() == "doubao":
            audio = await _doubao_tts(settings, text, voice)
        else:
            audio = await _xunfei_tts(settings, text, voice)
    except (httpx.HTTPError, OSError, RuntimeError, ValueError, TypeError) as error:
        raise APIError(502, "tts_failed", "语音合成服务暂时不可用") from error
    return Response(content=audio, media_type=_content_type(settings), headers={"Cache-Control": "no-store"})


@router.get("/speech/realtime")
async def realtime_probe(settings: Settings = Depends(get_app_settings), account: Account = Depends(get_current_account)) -> None:
    del account
    if not settings.speech_realtime_enabled or not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
        raise APIError(501, "speech_not_enabled", "当前后端未配置讯飞语音识别")
    raise APIError(426, "websocket_required", "语音识别需要 WebSocket 连接")


@router.websocket("/speech/realtime")
async def realtime(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    await websocket.accept()
    if not settings.speech_realtime_enabled or not (settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret):
        await websocket.send_json({"type": "error", "code": "speech_not_enabled", "message": "当前后端未配置讯飞语音识别"})
        await websocket.close(code=1008)
        return
    try:
        import websockets
        async with websockets.connect(_realtime_signed_url(settings), open_timeout=10) as upstream:
            await websocket.send_json({"type": "ready"})
            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                    if message.get("text") is not None:
                        payload = json.loads(message["text"])
                        if payload.get("type") == "stop":
                            await upstream.send(json.dumps({"end": True}))
                        elif payload.get("type") == "start":
                            await upstream.send(json.dumps({"lang": payload.get("language", "autodialect"), "audio_encode": "pcm_s16le", "samplerate": payload.get("sample_rate", 16000)}))
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
            async def upstream_to_client() -> None:
                async for raw in upstream:
                    if isinstance(raw, bytes):
                        continue
                    payload = json.loads(raw)
                    text = str(payload.get("text") or "")
                    if text:
                        await websocket.send_json({"type": "final", "text": text})
            import asyncio
            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except WebSocketDisconnect:
        return
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        logger.warning("speech realtime upstream failed", exc_info=True)
        try:
            await websocket.close()
        except (OSError, RuntimeError):
            pass


def _realtime_signed_url(settings: Settings) -> str:
    base = settings.xunfei_rtasr_base_url.rstrip("/")
    path = settings.xunfei_rtasr_path.strip() or "/ast/communicate/v1"
    query = {"appId": settings.xunfei_app_id, "accessKeyId": settings.xunfei_api_key, "utc": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"), "audio_encode": "pcm_s16le", "lang": "autodialect", "samplerate": "16000"}
    signing = urlencode(sorted(query.items()))
    query["signature"] = base64.b64encode(hmac.new(settings.xunfei_api_secret.encode(), signing.encode(), hashlib.sha1).digest()).decode()
    return f"{base}{path}?{urlencode(query)}"
