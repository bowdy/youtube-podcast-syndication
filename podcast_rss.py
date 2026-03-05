"""Generate Apple/Spotify-compliant RSS 2.0 XML with iTunes namespace tags."""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime

# Register namespace prefixes so output uses itunes: and atom: instead of ns0:/ns1:
ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
from podcast_config import (
    PODCAST_TITLE,
    PODCAST_DESCRIPTION,
    PODCAST_AUTHOR,
    PODCAST_EMAIL,
    PODCAST_WEBSITE,
    PODCAST_LANGUAGE,
    PODCAST_CATEGORIES,
    PODCAST_EXPLICIT,
)


def _format_duration(seconds: int) -> str:
    """Format seconds as HH:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _parse_date(date_str: str) -> datetime:
    """Parse an ISO date string into a datetime object."""
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def generate_rss_xml(episodes: list[dict], base_url: str) -> str:
    """Build a complete podcast RSS 2.0 XML string.

    Args:
        episodes: List of episode metadata dicts (already sorted newest-first).
        base_url: The public base URL of the Modal app (e.g. https://xxx.modal.run).

    Returns:
        UTF-8 encoded XML string.
    """
    ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    ATOM_NS = "http://www.w3.org/2005/Atom"

    rss = ET.Element("rss", {
        "version": "2.0",
    })

    channel = ET.SubElement(rss, "channel")

    # -- Channel-level elements --
    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "link").text = PODCAST_WEBSITE
    ET.SubElement(channel, "description").text = PODCAST_DESCRIPTION
    ET.SubElement(channel, "language").text = PODCAST_LANGUAGE
    ET.SubElement(channel, "generator").text = "ManyForce Podcast Engine"

    # Last build date
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )

    # Atom self-link (required by Apple)
    rss_url = f"{base_url}/rss"
    ET.SubElement(channel, f"{{{ATOM_NS}}}link", {
        "href": rss_url,
        "rel": "self",
        "type": "application/rss+xml",
    })

    # iTunes tags
    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = PODCAST_AUTHOR
    ET.SubElement(channel, f"{{{ITUNES_NS}}}summary").text = PODCAST_DESCRIPTION
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = (
        "true" if PODCAST_EXPLICIT else "false"
    )

    owner = ET.SubElement(channel, f"{{{ITUNES_NS}}}owner")
    ET.SubElement(owner, f"{{{ITUNES_NS}}}name").text = PODCAST_AUTHOR
    ET.SubElement(owner, f"{{{ITUNES_NS}}}email").text = PODCAST_EMAIL

    # Artwork
    artwork_url = f"{base_url}/artwork.jpg"
    ET.SubElement(channel, f"{{{ITUNES_NS}}}image", {"href": artwork_url})
    image_el = ET.SubElement(channel, "image")
    ET.SubElement(image_el, "url").text = artwork_url
    ET.SubElement(image_el, "title").text = PODCAST_TITLE
    ET.SubElement(image_el, "link").text = PODCAST_WEBSITE

    # Categories
    for cat in PODCAST_CATEGORIES:
        cat_el = ET.SubElement(
            channel, f"{{{ITUNES_NS}}}category", {"text": cat["category"]}
        )
        if cat.get("subcategory"):
            ET.SubElement(cat_el, f"{{{ITUNES_NS}}}category", {
                "text": cat["subcategory"]
            })

    # -- Episodes --
    for ep in episodes:
        item = ET.SubElement(channel, "item")

        ep_title = ep.get("podcast_title", ep.get("title", "Untitled"))
        ET.SubElement(item, "title").text = ep_title

        description = ep.get("podcast_description", ep.get("description", ""))
        ET.SubElement(item, "description").text = description
        ET.SubElement(item, f"{{{ITUNES_NS}}}summary").text = description

        # Enclosure (MP3)
        episode_id = ep["episode_id"]
        mp3_url = f"{base_url}/episode/{episode_id}.mp3"
        file_size = ep.get("mp3_file_size", 0)
        ET.SubElement(item, "enclosure", {
            "url": mp3_url,
            "length": str(file_size),
            "type": "audio/mpeg",
        })

        # GUID
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = episode_id

        # Pub date
        pub_date = _parse_date(ep.get("publish_date", ""))
        ET.SubElement(item, "pubDate").text = format_datetime(pub_date)

        # Duration
        duration = ep.get("duration_seconds", 0)
        if duration:
            ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = _format_duration(
                duration
            )

        # Episode/season numbers
        if ep.get("episode_number"):
            ET.SubElement(item, f"{{{ITUNES_NS}}}episode").text = str(
                ep["episode_number"]
            )
        if ep.get("season_number"):
            ET.SubElement(item, f"{{{ITUNES_NS}}}season").text = str(
                ep["season_number"]
            )

        # Explicit
        ET.SubElement(item, f"{{{ITUNES_NS}}}explicit").text = (
            "true" if ep.get("explicit", False) else "false"
        )

        # Link back to website
        ET.SubElement(item, "link").text = PODCAST_WEBSITE

    # Serialize to string
    ET.indent(rss, space="  ")
    xml_bytes = ET.tostring(rss, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes
