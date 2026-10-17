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

target = Path(__file__).resolve().parents[1] / "assets" / "asolar.ico"
target.parent.mkdir(exist_ok=True)
image.save(target, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(target)
