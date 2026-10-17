"""Buduje wielorozmiarową ikonę Windows z firmowego znaku ASOLAR."""

from pathlib import Path
from PIL import Image, ImageDraw


SIZE = 256
image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=55, fill="#123e30")

panel = [(48, 156), (208, 156), (178, 76), (78, 76)]
draw.polygon(panel, fill="#f5c84c")
for y in (102, 130):
    left = 78 - (y - 76) * 30 / 80
    right = 178 + (y - 76) * 30 / 80
    draw.line((left, y, right, y), fill="#123e30", width=9)
draw.line((104, 76, 90, 156), fill="#123e30", width=9)
draw.line((152, 76, 166, 156), fill="#123e30", width=9)
draw.line((128, 158, 128, 208), fill="white", width=13)
draw.line((90, 210, 166, 210), fill="white", width=13)

ROOT = Path(__file__).resolve().parents[1]
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# Ikona Windows: launcher C (assets) oraz aplikacja Electron (desktop/build).
for target in (ROOT / "assets" / "asolar.ico", ROOT / "desktop" / "build" / "icon.ico"):
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="ICO", sizes=ICO_SIZES)
    print(target)

# PNG dla PWA (Android/iOS) i electron-builder.
for size, target in ((192, ROOT / "frontend" / "public" / "icon-192.png"), (512, ROOT / "frontend" / "public" / "icon-512.png"), (512, ROOT / "desktop" / "build" / "icon.png")):
    target.parent.mkdir(parents=True, exist_ok=True)
    image.resize((size, size), Image.LANCZOS).save(target, format="PNG")
    print(target)
