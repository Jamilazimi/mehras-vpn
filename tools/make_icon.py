"""
ساخت آیکون برنامه (سپر با حرف «م») در assets/icon.ico و icon.png
اجرا: python tools/make_icon.py
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT = ROOT / "fonts" / "Vazirmatn-Bold.ttf"
SIZE = 512

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def shield_path(size, inset=0.10):
    """مسیر سپر (بالا صاف، پایین نوک‌تیز) به‌صورت چندضلعی نرم."""
    s = size
    top = s * inset
    bottom = s - s * inset
    left = s * inset
    right = s - s * inset
    pts = [
        (left, top + s * 0.06),
        (s * 0.5, top),
        (right, top + s * 0.06),
        (right, s * 0.52),
        (s * 0.5, bottom),
        (left, s * 0.52),
    ]
    return pts


def main():
    ASSETS.mkdir(exist_ok=True)
    # پس‌زمینه‌ی گرد با گرادیان آبی → فیروزه‌ای
    base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad = Image.new("RGBA", (SIZE, SIZE))
    gd = ImageDraw.Draw(grad)
    for y in range(SIZE):
        for_x = y / SIZE
        r = int(0x4C + (0x22 - 0x4C) * for_x)
        g = int(0x8D + (0xD3 - 0x8D) * for_x)
        b = int(0xFF + (0xEE - 0xFF) * for_x)
        gd.line([(0, y), (SIZE, y)], fill=(r, g, b, 255))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.24), fill=255)
    base.paste(grad, (0, 0), mask)

    # سپر سفید نیمه‌شفاف
    shield = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shield)
    sd.polygon(shield_path(SIZE), fill=(255, 255, 255, 235))
    base.alpha_composite(shield)

    # حرف «م» فیروزه‌ای داخل سپر
    draw = ImageDraw.Draw(base)
    try:
        font = ImageFont.truetype(str(FONT), int(SIZE * 0.42))
    except Exception:
        font = ImageFont.load_default()
    text = "م"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((SIZE - tw) / 2 - bbox[0], (SIZE - th) / 2 - bbox[1] - SIZE * 0.02),
              text, font=font, fill=(8, 26, 58, 255))

    # خروجی‌ها
    base.save(ASSETS / "icon.png")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    base.save(ASSETS / "icon.ico", sizes=sizes)
    print("written:", ASSETS / "icon.ico")
    print("written:", ASSETS / "icon.png")


if __name__ == "__main__":
    main()
