"""Web brand images from the app icon: favicons / PWA icons and the social-share card (og.png).

    python scripts/make_brand_images.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "mobile" / "assets" / "icon" / "icon.png"
OUT = ROOT / "frontend"


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    for name in (("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def main() -> None:
    icon = Image.open(ICON).convert("RGBA")
    for size in (192, 512):
        icon.resize((size, size), Image.LANCZOS).save(OUT / f"icon-{size}.png", optimize=True)
    icon.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png", optimize=True)

    # 1200x630 share card: dark background with a soft teal glow, the icon and the promise.
    W, H = 1200, 630
    card = Image.new("RGBA", (W, H), (7, 11, 20, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-200, 180, 700, 900), fill=(45, 212, 191, 70))
    card = Image.alpha_composite(card, glow.filter(ImageFilter.GaussianBlur(120)))
    small = icon.resize((300, 300), Image.LANCZOS)
    mask = Image.new("L", small.size, 0)  # the icon file has square corners: round them like the app icon
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 299, 299), radius=66, fill=255)
    small.putalpha(Image.composite(small.getchannel("A"), mask, mask))
    card.alpha_composite(small, (90, 165))
    d = ImageDraw.Draw(card)
    d.text((450, 180), "Dalili", font=font(104), fill=(232, 238, 252))
    d.text((454, 310), "AI Travel Planner", font=font(52), fill=(61, 224, 208))
    d.text((456, 400), "Real flights, hotels and places.", font=font(34, bold=False), fill=(159, 176, 207))
    d.text((456, 448), "A checked day-by-day plan in a minute.", font=font(34, bold=False), fill=(159, 176, 207))
    card.convert("RGB").save(OUT / "og.png", optimize=True)
    print("wrote icon-192.png, icon-512.png, apple-touch-icon.png, og.png")


if __name__ == "__main__":
    main()
