# Podcast configuration constants

PODCAST_TITLE = "The ManyForce AI Podcast"
PODCAST_DESCRIPTION = (
    "AI and entrepreneurship insights from ManyForce. "
    "We break down the latest in artificial intelligence, automation, "
    "and building businesses powered by AI. "
    "Learn more at https://manyforce.com"
)
PODCAST_AUTHOR = "ManyForce"
PODCAST_EMAIL = "podcast@manyforce.com"
PODCAST_WEBSITE = "https://manyforce.com"
PODCAST_LANGUAGE = "en-us"
PODCAST_CATEGORIES = [
    {"category": "Technology", "subcategory": "Artificial Intelligence"},
    {"category": "Business", "subcategory": "Entrepreneurship"},
]
PODCAST_EXPLICIT = False
PODCAST_YOUTUBE_CHANNEL = "https://www.youtube.com/@bowdler8"

# Modal infrastructure
MODAL_APP_NAME = "podcast-app"
VOLUME_NAME = "podcast-storage"
VOLUME_MOUNT = "/data/podcast"

# Audio settings
MP3_BITRATE = "192"  # kbps - good balance for spoken word
