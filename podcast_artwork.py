"""One-time script to generate podcast cover art and upload to Modal Volume.

Run: modal run podcast_artwork.py
"""

import modal

# Inline constants to keep this script self-contained (no local imports needed)
VOLUME_NAME = "podcast-storage"
VOLUME_MOUNT = "/data/podcast"

app = modal.App("podcast-artwork-generator")

image = modal.Image.debian_slim().apt_install("fonts-dejavu-core").pip_install("Pillow")
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

ARTWORK_DIR = f"{VOLUME_MOUNT}/artwork"


@app.function(image=image, volumes={VOLUME_MOUNT: volume})
def generate_artwork():
    """Generate a 3000x3000 podcast cover image."""
    import os
    from PIL import Image, ImageDraw, ImageFont

    os.makedirs(ARTWORK_DIR, exist_ok=True)

    size = 3000
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)

    # Background gradient effect (dark blue to dark purple)
    for y in range(size):
        r = int(15 + (25 * y / size))
        g = int(10 + (5 * y / size))
        b = int(40 + (60 * y / size))
        draw.line([(0, y), (size, y)], fill=(r, g, b))

    # Decorative elements - circuit-like pattern for AI theme
    accent_color = (0, 200, 255)  # Cyan accent
    for i in range(0, size, 150):
        draw.line([(i, 0), (i, size)], fill=(30, 30, 60), width=1)
        draw.line([(0, i), (size, i)], fill=(30, 30, 60), width=1)

    # Glowing dots at intersections
    for x in range(0, size, 300):
        for y in range(0, size, 300):
            draw.ellipse(
                [x - 4, y - 4, x + 4, y + 4],
                fill=(0, 150, 200, 128),
            )

    # Central area - darker rectangle for text backdrop
    margin = 300
    draw.rounded_rectangle(
        [margin, size // 2 - 500, size - margin, size // 2 + 500],
        radius=60,
        fill=(10, 10, 30),
        outline=accent_color,
        width=4,
    )

    # Text - use default font at large sizes
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 180)
        subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 100)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 70)
    except (OSError, IOError):
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # "THE MANYFORCE" text
    draw.text(
        (size // 2, size // 2 - 300),
        "THE MANYFORCE",
        fill=(255, 255, 255),
        font=title_font,
        anchor="mm",
    )

    # "AI PODCAST" text
    draw.text(
        (size // 2, size // 2 - 80),
        "AI PODCAST",
        fill=accent_color,
        font=title_font,
        anchor="mm",
    )

    # Horizontal divider
    draw.line(
        [(margin + 100, size // 2 + 80), (size - margin - 100, size // 2 + 80)],
        fill=accent_color,
        width=3,
    )

    # Tagline
    draw.text(
        (size // 2, size // 2 + 200),
        "AI & Entrepreneurship",
        fill=(180, 180, 200),
        font=subtitle_font,
        anchor="mm",
    )

    # Website
    draw.text(
        (size // 2, size // 2 + 370),
        "manyforce.com",
        fill=(100, 180, 220),
        font=small_font,
        anchor="mm",
    )

    # Save
    output_path = f"{ARTWORK_DIR}/cover.jpg"
    img.save(output_path, "JPEG", quality=95)
    volume.commit()

    file_size = os.path.getsize(output_path)
    print(f"Artwork saved to {output_path} ({file_size / 1024:.0f} KB)")
    return {"path": output_path, "size": file_size}


@app.local_entrypoint()
def main():
    result = generate_artwork.remote()
    print(f"Done! {result}")
