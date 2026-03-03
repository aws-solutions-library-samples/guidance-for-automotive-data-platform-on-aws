"""Slide 5: The Connected Vehicle Opportunity"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from theme import *

img, draw = new_slide()
draw_title(draw, "THE CONNECTED VEHICLE OPPORTUNITY", "Why connected vehicle platforms matter more than ever")

# Stat cards — horizontal
stats = [
    ("95%", "of new vehicles\nconnected by 2030", "McKinsey", SKY),
    ("470M", "connected cars\non the road by 2025", "Statista", GREEN),
    ("$100B+", "connected car services\nmarket by 2030", "McKinsey", ORANGE),
    ("25 GB", "of data per vehicle\nper hour", "Intel / Frost & Sullivan", YELLOW),
]

sw = (W - 230) // 4
sy = 145
for i, (num, desc, source, color) in enumerate(stats):
    x = 90 + i * (sw + 16)
    soft_card(draw, x, sy, sw, 155, accent=color)
    draw.text((x+24, sy+18), num, fill=color, font=F[40])
    for j, line in enumerate(desc.split("\n")):
        draw.text((x+24, sy+72 + j*22), line, fill=WHITE, font=F[16])
    draw.text((x+24, sy+130), source, fill=MUTED, font=F[12])

# Evolution: Yesterday → Today → Tomorrow
ey = 325
ew = (W - 230) // 3
evolutions = [
    ("YESTERDAY", RED, ["Basic telematics", "Reactive maintenance", "One-way data", "Siloed systems"]),
    ("TODAY", YELLOW, ["Real-time connectivity", "Predictive analytics", "Bi-directional OTA", "Cloud-first platforms"]),
    ("TOMORROW", GREEN, ["Autonomous operations", "Personalized experiences", "Monetized data services", "AI-driven everything"]),
]

for i, (label, color, items) in enumerate(evolutions):
    x = 90 + i * (ew + 16)
    soft_card(draw, x, ey, ew, 210, accent=color)
    draw.text((x+24, ey+16), label, fill=color, font=F[20])
    for j, item in enumerate(items):
        draw.text((x+24, ey+55 + j*36), "→", fill=color, font=F[16])
        draw.text((x+48, ey+55 + j*36), item, fill=LIGHT, font=F[16])

    # Arrow between
    if i < 2:
        ax = x + ew + 2
        ay = ey + 105
        draw.line([(ax, ay), (ax+10, ay)], fill=MUTED, width=2)
        draw.polygon([(ax+10, ay-5), (ax+18, ay), (ax+10, ay+5)], fill=MUTED)

# Challenges
cy = 560
soft_card(draw, 90, cy, W-180, 140, accent=SKY)
draw.text((120, cy+14), "THE CHALLENGE", fill=SKY, font=F[22])

challenges = [
    ("📊  Data Explosion", "Vehicles generate TBs daily — legacy infra can't keep up"),
    ("🔧  Legacy Debt", "On-prem systems built for thousands, not millions"),
    ("💰  Cost Pressure", "Custom stacks drain engineering budgets"),
    ("⚡  Speed to Market", "Competitors ship features in weeks, not quarters"),
]
cw2 = (W - 260) // 2
for i, (title, desc) in enumerate(challenges):
    col = i % 2
    row = i // 2
    x = 120 + col * cw2
    y = cy + 52 + row * 42
    draw.text((x, y), title, fill=WHITE, font=F[16])
    draw.text((x+210, y+1), desc, fill=LIGHT, font=F[15])

# Hook
hy = H - 65
soft_card(draw, 90, hy, W-180, 36)
draw.text((120, hy+8), "The question isn't whether to modernize —", fill=LIGHT, font=F[18])
draw.text((660, hy+8), "it's how fast you can move.", fill=ORANGE, font=F[18])

draw_footer(draw)
save(img, "slide5_opportunity.png")
