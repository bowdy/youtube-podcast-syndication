import modal
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import os
import uuid
from datetime import datetime, timezone

from podcast_config import (
    MODAL_APP_NAME,
    VOLUME_NAME,
    VOLUME_MOUNT,
    MP3_BITRATE,
    PODCAST_TITLE,
    PODCAST_DESCRIPTION,
    PODCAST_AUTHOR,
    PODCAST_EMAIL,
    PODCAST_WEBSITE,
    PODCAST_LANGUAGE,
    PODCAST_CATEGORIES,
    PODCAST_EXPLICIT,
)

# ---------------------------------------------------------------------------
# Modal infrastructure
# ---------------------------------------------------------------------------

app = modal.App(MODAL_APP_NAME)

image = (
    modal.Image.debian_slim()
    .apt_install("ffmpeg")
    .pip_install(
        "yt-dlp[default]",
        "anthropic",
        "fastapi",
        "pydantic",
        "httpx",
    )
    .add_local_python_source("podcast_config", "podcast_rss")
)

volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

EPISODES_DIR = f"{VOLUME_MOUNT}/episodes"
METADATA_DIR = f"{VOLUME_MOUNT}/metadata"
ARTWORK_DIR = f"{VOLUME_MOUNT}/artwork"
FEED_INDEX_PATH = f"{VOLUME_MOUNT}/feed_index.json"

# ---------------------------------------------------------------------------
# FastAPI web app (served via Modal ASGI)
# ---------------------------------------------------------------------------

web_app = FastAPI(title="ManyForce Podcast API")


def verify_bearer_token(authorization: Optional[str]) -> None:
    """Verify Bearer token on protected endpoints."""
    expected = os.environ.get("API_AUTH_TOKEN")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    if authorization.replace("Bearer ", "") != expected:
        raise HTTPException(status_code=403, detail="Invalid authentication token")


def _ensure_dirs():
    """Create volume subdirectories if they don't exist."""
    for d in [EPISODES_DIR, METADATA_DIR, ARTWORK_DIR]:
        os.makedirs(d, exist_ok=True)


def _load_feed_index() -> list:
    """Load the feed index (list of published episodes) from the volume."""
    if os.path.exists(FEED_INDEX_PATH):
        with open(FEED_INDEX_PATH, "r") as f:
            return json.load(f)
    return []


def _save_feed_index(index: list) -> None:
    """Save the feed index to the volume."""
    with open(FEED_INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ExtractAudioRequest(BaseModel):
    youtube_url: str
    episode_id: Optional[str] = None


class GenerateNotesRequest(BaseModel):
    episode_id: str
    title: str
    description: str
    duration_seconds: int
    youtube_url: str
    channel_name: str = ""
    custom_links: list[str] = []


class PublishEpisodeRequest(BaseModel):
    episode_id: str
    podcast_title: str
    podcast_description: str
    episode_number: Optional[int] = None
    season_number: Optional[int] = None
    explicit: bool = False
    publish_date: Optional[str] = None  # ISO format; defaults to now


# ---------------------------------------------------------------------------
# POST /extract-audio
# ---------------------------------------------------------------------------

@web_app.post("/extract-audio")
async def extract_audio(data: ExtractAudioRequest, authorization: str = Header(None)):
    """Download audio from a YouTube video, convert to MP3, save to volume."""
    import traceback

    try:
        verify_bearer_token(authorization)
        _ensure_dirs()

        import yt_dlp

        episode_id = data.episode_id or uuid.uuid4().hex[:12]
        mp3_path = f"{EPISODES_DIR}/{episode_id}.mp3"

        # Use cookies if available (needed to bypass YouTube bot detection on cloud IPs)
        cookies_path = f"{VOLUME_MOUNT}/cookies.txt"
        has_cookies = os.path.exists(cookies_path)

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{EPISODES_DIR}/{episode_id}.%(ext)s",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": MP3_BITRATE,
                }
            ],
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {"youtube": {"player_client": ["tv", "web"]}},
        }
        if has_cookies:
            ydl_opts["cookiefile"] = cookies_path

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(data.youtube_url, download=True)
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}

    # Get file size
    file_size = os.path.getsize(mp3_path) if os.path.exists(mp3_path) else 0

    metadata = {
        "episode_id": episode_id,
        "title": info.get("title", "Untitled"),
        "description": info.get("description", ""),
        "duration_seconds": info.get("duration", 0),
        "youtube_url": data.youtube_url,
        "thumbnail_url": info.get("thumbnail", ""),
        "channel_name": info.get("uploader", ""),
        "upload_date": info.get("upload_date", ""),
        "mp3_filename": f"{episode_id}.mp3",
        "mp3_file_size": file_size,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "status": "extracted",
    }

    with open(f"{METADATA_DIR}/{episode_id}.json", "w") as f:
        json.dump(metadata, f, indent=2)

    volume.commit()

    return metadata


# ---------------------------------------------------------------------------
# POST /upload-audio -- Upload a locally-downloaded MP3 + metadata
# ---------------------------------------------------------------------------

class UploadAudioRequest(BaseModel):
    episode_id: Optional[str] = None
    title: str
    description: str = ""
    duration_seconds: int = 0
    youtube_url: str = ""
    channel_name: str = ""
    thumbnail_url: str = ""
    upload_date: str = ""
    mp3_base64: str  # Base64-encoded MP3 data


@web_app.post("/upload-audio")
async def upload_audio(data: UploadAudioRequest, authorization: str = Header(None)):
    """Upload a locally-downloaded MP3 file with metadata. Use this when cloud
    download is blocked by YouTube. The local helper script handles yt-dlp."""
    import base64

    verify_bearer_token(authorization)
    _ensure_dirs()

    episode_id = data.episode_id or uuid.uuid4().hex[:12]
    mp3_path = f"{EPISODES_DIR}/{episode_id}.mp3"

    # Decode and write MP3
    mp3_bytes = base64.b64decode(data.mp3_base64)
    with open(mp3_path, "wb") as f:
        f.write(mp3_bytes)

    file_size = len(mp3_bytes)

    metadata = {
        "episode_id": episode_id,
        "title": data.title,
        "description": data.description,
        "duration_seconds": data.duration_seconds,
        "youtube_url": data.youtube_url,
        "thumbnail_url": data.thumbnail_url,
        "channel_name": data.channel_name,
        "upload_date": data.upload_date,
        "mp3_filename": f"{episode_id}.mp3",
        "mp3_file_size": file_size,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "status": "extracted",
    }

    with open(f"{METADATA_DIR}/{episode_id}.json", "w") as f:
        json.dump(metadata, f, indent=2)

    volume.commit()

    return metadata


# ---------------------------------------------------------------------------
# POST /generate-notes
# ---------------------------------------------------------------------------

@web_app.post("/generate-notes")
async def generate_notes(data: GenerateNotesRequest, authorization: str = Header(None)):
    """Generate AI-powered podcast show notes using Claude."""
    verify_bearer_token(authorization)

    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    extra_links = "\n".join(f"- {link}" for link in data.custom_links) if data.custom_links else ""

    user_prompt = f"""Generate podcast show notes for the following YouTube video being published as a podcast episode.

Video Title: {data.title}
Channel: {data.channel_name}
Duration: {data.duration_seconds // 60} minutes
YouTube URL: {data.youtube_url}

Video Description:
{data.description[:3000]}

{f"Additional links to include:{chr(10)}{extra_links}" if extra_links else ""}
"""

    system_prompt = """You are writing podcast show notes for "The ManyForce AI Podcast".

Your output must be valid JSON with these exact keys:
- "podcast_title": A compelling podcast episode title (can differ from the video title)
- "podcast_description": 2-3 paragraphs summarizing the episode content. Plain text with line breaks. No HTML.
- "key_topics": An array of 3-7 key topics discussed
- "timestamps": An array of objects with "time" (MM:SS) and "label" keys, if extractable from the description. Empty array if none found.

IMPORTANT: Always end the podcast_description with this footer (separated by two newlines):

---
Learn more at https://manyforce.com
Watch the video version: [include the YouTube URL]

Keep the description engaging but concise -- it appears in podcast apps with limited space."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    response_text = message.content[0].text

    # Parse the JSON response
    try:
        # Handle case where response might have markdown code fences
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        notes = json.loads(cleaned)
    except json.JSONDecodeError:
        notes = {
            "podcast_title": data.title,
            "podcast_description": response_text,
            "key_topics": [],
            "timestamps": [],
        }

    notes["episode_id"] = data.episode_id
    notes["youtube_url"] = data.youtube_url

    return notes


# ---------------------------------------------------------------------------
# POST /publish-episode
# ---------------------------------------------------------------------------

@web_app.post("/publish-episode")
async def publish_episode(data: PublishEpisodeRequest, authorization: str = Header(None)):
    """Finalize episode metadata and add to the RSS feed index."""
    verify_bearer_token(authorization)
    _ensure_dirs()

    metadata_path = f"{METADATA_DIR}/{data.episode_id}.json"
    if not os.path.exists(metadata_path):
        raise HTTPException(status_code=404, detail=f"Episode {data.episode_id} not found")

    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    publish_date = data.publish_date or datetime.now(timezone.utc).isoformat()

    metadata.update({
        "podcast_title": data.podcast_title,
        "podcast_description": data.podcast_description,
        "episode_number": data.episode_number,
        "season_number": data.season_number,
        "explicit": data.explicit,
        "publish_date": publish_date,
        "status": "published",
    })

    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Update feed index
    feed_index = _load_feed_index()

    # Remove existing entry for this episode if re-publishing
    feed_index = [ep for ep in feed_index if ep.get("episode_id") != data.episode_id]

    feed_index.insert(0, {
        "episode_id": data.episode_id,
        "podcast_title": data.podcast_title,
        "publish_date": publish_date,
    })

    # Sort by publish date descending
    feed_index.sort(key=lambda x: x.get("publish_date", ""), reverse=True)
    _save_feed_index(feed_index)

    volume.commit()

    return {
        "episode_id": data.episode_id,
        "status": "published",
        "publish_date": publish_date,
        "total_episodes": len(feed_index),
    }


# ---------------------------------------------------------------------------
# GET /rss -- Public podcast RSS feed
# ---------------------------------------------------------------------------

@web_app.get("/rss")
async def rss_feed(request: Request):
    """Serve the podcast RSS feed. Public -- no auth required."""
    from podcast_rss import generate_rss_xml

    volume.reload()

    feed_index = _load_feed_index()

    # Load full metadata for each published episode
    episodes = []
    for entry in feed_index:
        meta_path = f"{METADATA_DIR}/{entry['episode_id']}.json"
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                meta = json.load(f)
            if meta.get("status") == "published":
                episodes.append(meta)

    # Determine base URL from the request
    base_url = str(request.base_url).rstrip("/")

    xml_content = generate_rss_xml(episodes, base_url)

    return Response(content=xml_content, media_type="application/rss+xml; charset=utf-8")


# ---------------------------------------------------------------------------
# GET /episode/{episode_id}.mp3 -- Public MP3 serving
# ---------------------------------------------------------------------------

@web_app.get("/episode/{episode_id}.mp3")
async def serve_episode(episode_id: str):
    """Stream an episode MP3 file. Public -- no auth required."""
    volume.reload()

    mp3_path = f"{EPISODES_DIR}/{episode_id}.mp3"
    if not os.path.exists(mp3_path):
        raise HTTPException(status_code=404, detail="Episode not found")

    file_size = os.path.getsize(mp3_path)

    def stream_file():
        with open(mp3_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        stream_file(),
        media_type="audio/mpeg",
        headers={
            "Content-Length": str(file_size),
            "Content-Disposition": f'inline; filename="{episode_id}.mp3"',
        },
    )


# ---------------------------------------------------------------------------
# GET /artwork.jpg -- Public artwork serving
# ---------------------------------------------------------------------------

@web_app.get("/artwork.jpg")
async def serve_artwork():
    """Serve the podcast cover art. Public -- no auth required."""
    volume.reload()

    artwork_path = f"{ARTWORK_DIR}/cover.jpg"
    if not os.path.exists(artwork_path):
        raise HTTPException(status_code=404, detail="Artwork not found")

    file_size = os.path.getsize(artwork_path)

    def stream_file():
        with open(artwork_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        stream_file(),
        media_type="image/jpeg",
        headers={"Content-Length": str(file_size)},
    )


# ---------------------------------------------------------------------------
# POST /upload-cookies -- Upload YouTube cookies for bot-detection bypass
# ---------------------------------------------------------------------------

class CookiesRequest(BaseModel):
    cookies_txt: str  # Contents of cookies.txt in Netscape format


@web_app.post("/upload-cookies")
async def upload_cookies(data: CookiesRequest, authorization: str = Header(None)):
    """Upload YouTube cookies.txt to bypass bot detection on cloud IPs."""
    verify_bearer_token(authorization)
    _ensure_dirs()

    cookies_path = f"{VOLUME_MOUNT}/cookies.txt"
    with open(cookies_path, "w") as f:
        f.write(data.cookies_txt)

    volume.commit()
    return {"status": "cookies uploaded", "path": cookies_path}


# ---------------------------------------------------------------------------
# DELETE /episode/{episode_id} -- Remove an episode from the feed + volume
# ---------------------------------------------------------------------------

@web_app.delete("/episode/{episode_id}")
async def delete_episode(episode_id: str, authorization: str = Header(None)):
    """Delete an episode's MP3, metadata, and feed index entry."""
    verify_bearer_token(authorization)
    _ensure_dirs()

    mp3_path = f"{EPISODES_DIR}/{episode_id}.mp3"
    meta_path = f"{METADATA_DIR}/{episode_id}.json"

    deleted = []
    if os.path.exists(mp3_path):
        os.remove(mp3_path)
        deleted.append("mp3")
    if os.path.exists(meta_path):
        os.remove(meta_path)
        deleted.append("metadata")

    # Remove from feed index
    feed_index = _load_feed_index()
    original_len = len(feed_index)
    feed_index = [ep for ep in feed_index if ep.get("episode_id") != episode_id]
    if len(feed_index) < original_len:
        deleted.append("feed_entry")
    _save_feed_index(feed_index)

    volume.commit()

    return {
        "episode_id": episode_id,
        "deleted": deleted,
        "remaining_episodes": len(feed_index),
    }


# ---------------------------------------------------------------------------
# Modal ASGI entrypoint
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    secrets=[
        modal.Secret.from_name("anthropic-api-key"),
        modal.Secret.from_name("api-auth-token"),
    ],
    timeout=600,
)
@modal.asgi_app()
def serve():
    return web_app
