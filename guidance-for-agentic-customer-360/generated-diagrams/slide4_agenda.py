"""Slide 4: Today's Agenda"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from theme import *

img, draw = new_slide()
draw_title(draw, "TODAY'S AGENDA", "Vehicle Technology & Connected — Deep Dive")

# Strategic domains bar
dy = 135
soft_card(draw, 90, dy, W-180, 38)
draw.text((110, dy+9), "Strategic Domains:", fill=MUTED, font=F[15])
for i, (name, active) in enumerate([("Vehicle Technology", True), ("Connected", True), ("Product Engineering", False), ("Smart Manufacturing", False)]):
    x = 340 + i * 230
    color = SKY if active else MUTED
    if active:
        pill(draw, x, dy+6, name, color, F[14])
    else:
        draw.text((x+12, dy+10), name, fill=MUTED, font=F[14])

# Sections
sections = [
    ("01", "Connected", "Modernizing the connected vehicle stack", SKY,
     ["Cellular (ACS)", "Connectivity (IoT Core)", "Streaming (MSK)", "Processing (Flink)", "Observability"]),
    ("02", "Automotive Data Platform", "Turning vehicle data into actionable insights", GREEN,
     ["Data lake (S3)", "Analytics (Athena)", "ML & predictions (SageMaker)", "Data governance"]),
    ("03", "Digital Customer Experience", "Engaging customers across every touchpoint", PINK,
     ["Contact center (Connect)", "CRM integration", "Personalization", "After-sales"]),
    ("04", "Fleet Management", "Optimizing fleet operations at scale", PURPLE,
     ["Telematics & tracking", "Predictive maintenance", "Route optimization", "Driver safety"]),
]

sy = 200
sh = 185
gap = 18

# Timeline spine
spine_x = 130
draw.line([(spine_x, sy+30), (spine_x, sy + 4*(sh+gap) - gap - 30)], fill=BORDER, width=2)

for i, (num, title, subtitle, color, topics) in enumerate(sections):
    y = sy + i * (sh + gap)

    # Timeline node
    draw.ellipse([spine_x-8, y+sh//2-8, spine_x+8, y+sh//2+8], fill=color)
    draw.ellipse([spine_x-3, y+sh//2-3, spine_x+3, y+sh//2+3], fill=BG)

    # Number
    draw.text((80, y+sh//2-18), num, fill=color, font=F[32])

    # Card
    cx = 165
    cw = W - 260
    soft_card(draw, cx, y, cw, sh, accent=color)

    draw.text((cx+24, y+18), title, fill=WHITE, font=F[26])
    draw.text((cx+24, y+52), subtitle, fill=LIGHT, font=F[16])

    # Topic pills
    px = cx + 24
    py = y + 90
    for topic in topics:
        pw = pill(draw, px, py, topic, color, F[13])
        px += pw + 10
        if px > cx + cw - 100:
            py += 32
            px = cx + 24

draw_footer(draw)
save(img, "slide4_agenda.png")
