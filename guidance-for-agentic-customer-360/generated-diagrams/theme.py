"""Shared theme for all slides — modern, flowing, less boxy."""
from PIL import Image, ImageDraw, ImageFont
import math

W, H = 1920, 1080

# Palette
BG = (10, 14, 28)
SURFACE = (16, 22, 40)
CARD = (20, 28, 52)
BORDER = (35, 45, 72)
ORANGE = (255, 153, 0)
WHITE = (255, 255, 255)
LIGHT = (190, 200, 220)
MUTED = (110, 125, 150)
SKY = (56, 189, 248)
GREEN = (52, 211, 153)
PURPLE = (139, 92, 246)
PINK = (244, 114, 182)
YELLOW = (251, 191, 36)
RED = (248, 113, 113)

def get_font(size):
    for p in ["/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"]:
        try: return ImageFont.truetype(p, size)
        except: continue
    return ImageFont.load_default()

# Pre-load fonts
F = {s: get_font(s) for s in [11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 26, 28, 32, 36, 40, 44, 48, 56]}

def new_slide():
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    _draw_bg(draw)
    return img, draw

def _draw_bg(draw):
    # Subtle radial gradient from center
    for y in range(H):
        for x in range(0, W, 4):
            dist = math.sqrt((x - W*0.7)**2 + (y - H*0.3)**2) / (W*0.8)
            brightness = max(0, int(12 * (1 - dist)))
            if brightness > 0:
                c = (10 + brightness, 14 + brightness, 28 + brightness*2)
                draw.rectangle([x, y, x+3, y], fill=c)

    # Soft horizontal accent lines
    for y in [4, H-4]:
        for x in range(W):
            a = 1.0 - abs(x - W/2) / (W/2)
            c = int(255 * a * 0.3)
            draw.point((x, y), fill=(c, int(c*0.6), 0))

def draw_title(draw, title, subtitle):
    draw.text((90, 38), title, fill=ORANGE, font=F[44])
    draw.text((90, 92), subtitle, fill=LIGHT, font=F[22])
    # Soft underline
    for x in range(90, 600):
        a = 1.0 - (x - 90) / 510
        draw.point((x, 122), fill=(int(255*a*0.4), int(153*a*0.4), 0))

def draw_footer(draw):
    draw.text((90, H-22), "© 2026, Amazon Web Services, Inc. or its affiliates. All rights reserved.", fill=(50, 60, 80), font=F[12])

def pill(draw, x, y, text, color, font=None):
    """Draw a rounded pill with text, return width."""
    f = font or F[14]
    bbox = draw.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    pw = tw + 24
    ph = bbox[3] - bbox[1] + 14
    # Darker fill derived from color
    fill = (color[0]//8, color[1]//8, color[2]//8)
    draw.rounded_rectangle([x, y, x+pw, y+ph], radius=ph//2, fill=fill, outline=color)
    draw.text((x+12, y+5), text, fill=color, font=f)
    return pw

def soft_card(draw, x, y, w, h, accent=None, radius=16):
    """Draw a card with soft gradient feel."""
    draw.rounded_rectangle([x, y, x+w, y+h], radius=radius, fill=CARD)
    if accent:
        # Top accent line with fade
        for px in range(x+radius, x+w-radius):
            a = 1.0 - abs(px - (x+w/2)) / (w/2)
            c = tuple(int(v * a * 0.8) for v in accent)
            draw.point((px, y+1), fill=c)
            draw.point((px, y+2), fill=c)

def save(img, name):
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    img.save(out, "PNG", quality=95)
    print(f"Saved: {out}")
