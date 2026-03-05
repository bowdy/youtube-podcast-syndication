#!/opt/homebrew/opt/python@3.12/bin/python3.12
"""Local helper: download YouTube audio with yt-dlp on your Mac, then upload to Modal.

Usage:
    python3 local_extract.py "https://www.youtube.com/watch?v=VIDEO_ID"

Requires: pip3 install yt-dlp requests
"""

import sys
import os
import json
import base64
import tempfile
import subprocess
import requests

# Configuration
API_URL = "https://bowdy--podcast-app-serve.modal.run"
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

def get_token():
    """Read API_AUTH_TOKEN from .env file."""
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                if line.startswith("API_AUTH_TOKEN="):
                    return line.strip().split("=", 1)[1]
    raise ValueError(f"API_AUTH_TOKEN not found in {ENV_PATH}")


def extract_and_upload(youtube_url, episode_id=None):
    """Download audio locally with yt-dlp, then upload to Modal."""
    token = get_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = os.path.join(tmpdir, "audio.%(ext)s")

        # Step 1: Download with yt-dlp locally
        print(f"Downloading audio from: {youtube_url}")
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--format", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "192K",
            "--output", out_template,
            "--print-json",
            "--no-warnings",
            "--cookies-from-browser", "chrome",
            youtube_url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"yt-dlp error: {result.stderr}")
            sys.exit(1)

        # Parse metadata from yt-dlp JSON output
        info = json.loads(result.stdout.strip().split("\n")[-1])

        # Find the MP3 file
        mp3_path = os.path.join(tmpdir, "audio.mp3")
        if not os.path.exists(mp3_path):
            # yt-dlp might have used a different name
            for f in os.listdir(tmpdir):
                if f.endswith(".mp3"):
                    mp3_path = os.path.join(tmpdir, f)
                    break

        if not os.path.exists(mp3_path):
            print(f"Error: MP3 file not found in {tmpdir}")
            print(f"Files: {os.listdir(tmpdir)}")
            sys.exit(1)

        file_size = os.path.getsize(mp3_path)
        print(f"Downloaded: {info.get('title', 'Unknown')} ({file_size / 1024 / 1024:.1f} MB)")

        # Step 2: Base64 encode and upload
        print("Uploading to Modal...")
        with open(mp3_path, "rb") as f:
            mp3_base64 = base64.b64encode(f.read()).decode("ascii")

        payload = {
            "title": info.get("title", "Untitled"),
            "description": info.get("description", ""),
            "duration_seconds": info.get("duration", 0),
            "youtube_url": youtube_url,
            "thumbnail_url": info.get("thumbnail", ""),
            "channel_name": info.get("uploader", ""),
            "upload_date": info.get("upload_date", ""),
            "mp3_base64": mp3_base64,
        }
        if episode_id:
            payload["episode_id"] = episode_id

        resp = requests.post(f"{API_URL}/upload-audio", json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        result = resp.json()

        print(f"\nUploaded! Episode ID: {result['episode_id']}")
        print(f"Title: {result['title']}")
        print(f"Duration: {result['duration_seconds'] // 60} minutes")
        print(f"File size: {result['mp3_file_size'] / 1024 / 1024:.1f} MB")

        # Step 3: Generate show notes
        print("\nGenerating show notes with Claude AI...")
        notes_payload = {
            "episode_id": result["episode_id"],
            "title": result["title"],
            "description": result["description"],
            "duration_seconds": result["duration_seconds"],
            "youtube_url": result["youtube_url"],
            "channel_name": result["channel_name"],
        }
        resp = requests.post(f"{API_URL}/generate-notes", json=notes_payload, headers=headers, timeout=60)
        resp.raise_for_status()
        notes = resp.json()

        print(f"Podcast title: {notes['podcast_title']}")
        print(f"Key topics: {', '.join(notes.get('key_topics', []))}")

        # Step 4: Publish episode
        print("\nPublishing episode...")
        publish_payload = {
            "episode_id": result["episode_id"],
            "podcast_title": notes["podcast_title"],
            "podcast_description": notes["podcast_description"],
        }
        resp = requests.post(f"{API_URL}/publish-episode", json=publish_payload, headers=headers, timeout=30)
        resp.raise_for_status()
        pub = resp.json()

        print(f"Published! Total episodes: {pub['total_episodes']}")
        print(f"\nRSS Feed: {API_URL}/rss")
        print(f"Episode MP3: {API_URL}/episode/{result['episode_id']}.mp3")

        return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 local_extract.py <youtube_url> [episode_id]")
        sys.exit(1)

    url = sys.argv[1]
    ep_id = sys.argv[2] if len(sys.argv) > 2 else None
    extract_and_upload(url, ep_id)
