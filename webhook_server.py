#!/opt/homebrew/opt/python@3.12/bin/python3.12
"""Local webhook server for n8n → YouTube podcast pipeline.

Receives webhook calls from n8n (via Cloudflare Tunnel), downloads YouTube
audio locally (bypassing cloud IP blocks), then uploads to Modal and triggers
the full podcast pipeline (notes + publish).

Usage:
    python3.12 webhook_server.py          # Starts on port 8765
    python3.12 webhook_server.py 9000     # Custom port

Expose via Cloudflare Tunnel:
    cloudflared tunnel --url http://localhost:8765
"""

import sys
import os
import json
import base64
import tempfile
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# Configuration
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
API_URL = "https://bowdy--podcast-app-serve.modal.run"
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
PYTHON = "/opt/homebrew/opt/python@3.12/bin/python3.12"


def get_token():
    """Read API_AUTH_TOKEN from .env file."""
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                if line.startswith("API_AUTH_TOKEN="):
                    return line.strip().split("=", 1)[1]
    raise ValueError(f"API_AUTH_TOKEN not found in {ENV_PATH}")


def process_video(youtube_url):
    """Full pipeline: download locally → upload to Modal → generate notes → publish."""
    token = get_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = os.path.join(tmpdir, "audio.%(ext)s")

        # Step 1: Download with yt-dlp locally
        cmd = [
            PYTHON, "-m", "yt_dlp",
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
            return {"error": f"yt-dlp failed: {result.stderr}"}

        info = json.loads(result.stdout.strip().split("\n")[-1])

        # Find the MP3 file
        mp3_path = os.path.join(tmpdir, "audio.mp3")
        if not os.path.exists(mp3_path):
            for f in os.listdir(tmpdir):
                if f.endswith(".mp3"):
                    mp3_path = os.path.join(tmpdir, f)
                    break

        if not os.path.exists(mp3_path):
            return {"error": f"MP3 not found in {tmpdir}"}

        # Step 2: Upload to Modal
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

        resp = requests.post(f"{API_URL}/upload-audio", json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        upload_result = resp.json()

        episode_id = upload_result["episode_id"]

        # Step 3: Generate show notes
        notes_payload = {
            "episode_id": episode_id,
            "title": upload_result["title"],
            "description": upload_result["description"],
            "duration_seconds": upload_result["duration_seconds"],
            "youtube_url": upload_result["youtube_url"],
            "channel_name": upload_result["channel_name"],
        }
        resp = requests.post(f"{API_URL}/generate-notes", json=notes_payload, headers=headers, timeout=60)
        resp.raise_for_status()
        notes = resp.json()

        # Step 4: Publish episode
        publish_payload = {
            "episode_id": episode_id,
            "podcast_title": notes["podcast_title"],
            "podcast_description": notes["podcast_description"],
        }
        resp = requests.post(f"{API_URL}/publish-episode", json=publish_payload, headers=headers, timeout=30)
        resp.raise_for_status()
        pub = resp.json()

        return {
            "status": "published",
            "episode_id": episode_id,
            "podcast_title": notes["podcast_title"],
            "total_episodes": pub["total_episodes"],
            "rss_url": f"{API_URL}/rss",
            "mp3_url": f"{API_URL}/episode/{episode_id}.mp3",
        }


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/process-video":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not found. Use POST /process-video"}')
            return

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "Invalid JSON"}')
            return

        youtube_url = data.get("youtube_url")
        if not youtube_url:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "youtube_url is required"}')
            return

        print(f"Processing: {youtube_url}")

        try:
            result = process_video(youtube_url)
            status = 200 if "error" not in result else 500
        except Exception as e:
            result = {"error": str(e)}
            status = 500

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

        if status == 200:
            print(f"Published: {result.get('podcast_title', 'Unknown')}")
        else:
            print(f"Error: {result.get('error', 'Unknown')}")

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok", "service": "podcast-webhook"}')

    def log_message(self, format, *args):
        print(f"[webhook] {args[0]}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"Webhook server running on port {PORT}")
    print(f"Endpoint: POST http://localhost:{PORT}/process-video")
    print(f'Body: {{"youtube_url": "https://youtube.com/watch?v=..."}}')
    print()
    print("Expose with: cloudflared tunnel --url http://localhost:{PORT}")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()
