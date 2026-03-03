"""Preview of the challenge slide"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from theme import *

img, draw = new_slide()
draw_title(draw, "WHAT'S HOLDING YOU AT GEN 2?", "The barriers between cloud-connected and cloud-native & AI-enabled")

# Gen 2 → Gen 3 bar
soft_card(draw, 90, 140, 700, 38, accent=YELLOW)
draw.text((110, 148), "Gen 2: Cloud-Connected", fill=YELLOW, font=F[15])
draw.text((380, 148), "(where most OEMs are today)", fill=MUTED, font=F[13])

draw.text((810, 146), "→", fill=MUTED, font=F[22])

soft_card(draw, 860, 140, 700, 38, accent=GREEN)
draw.text((880, 148), "Gen 3: Cloud-Native & AI-Enabled", fill=GREEN, font=F[15])
draw.text((1210, 148), "(where you need to be)", fill=MUTED, font=F[13])

# 2x2 challenge grid
challenges = [
    ("📈", "Scaling Ceiling", "10x", "fleet growth expected", SKY,
     "Self-managed infra hits limits as fleets grow from thousands to millions of vehicles.",
     "Manual capacity planning", "Auto-scaling managed services"),
    ("🔧", "Ops Burden", "70%", "of eng time on infra", RED,
     "Engineering teams spend the majority of time maintaining infrastructure, not building features.",
     "Teams manage servers & pipelines", "Zero-ops fully managed services"),
    ("💰", "Cost Doesn't Scale", "Linear", "cost growth with fleet", YELLOW,
     "Self-managed cloud costs grow linearly with fleet size. No economies of scale.",
     "Pay for peak capacity 24/7", "Pay-as-you-go, scale to zero"),
    ("⚡", "Innovation Gap", "Weeks", "vs. quarters to ship", GREEN,
     "Competitors on managed services ship features in days. You're waiting on infra provisioning.",
     "Quarterly release cycles", "Continuous delivery in days"),
]

cw = 840
ch = 310
cgap = 40
cx = 90
cy = 200

for i, (icon, title, stat, stat_desc, color, desc, gen2, gen3) in enumerate(challenges):
    col = i % 2
    row = i // 2
    x = cx + col * (cw + cgap)
    y = cy + row * (ch + 20)

    soft_card(draw, x, y, cw, ch, accent=color)

    # Icon + title
    draw.text((x+16, y+12), icon, font=F[22])
    draw.text((x+48, y+14), title, fill=WHITE, font=F[22])

    # Stat - right side
    draw.text((x+cw-180, y+10), stat, fill=color, font=F[32])
    draw.text((x+cw-180, y+46), stat_desc, fill=MUTED, font=F[12])

    # Description
    # Word wrap manually
    words = desc.split()
    lines, line = [], ""
    for w in words:
        test = f"{line} {w}".strip()
        bbox = draw.textbbox((0, 0), test, font=F[14])
        if bbox[2] - bbox[0] > cw - 60:
            lines.append(line); line = w
        else:
            line = test
    if line: lines.append(line)
    for j, l in enumerate(lines):
        draw.text((x+20, y+70 + j*20), l, fill=LIGHT, font=F[14])

    # Gen 2 vs Gen 3 boxes at bottom
    bw = (cw - 50) // 2
    by = y + ch - 75

    # Gen 2
    draw.rounded_rectangle([x+12, by, x+12+bw, by+60], radius=8, fill=(12, 16, 30), outline=YELLOW)
    draw.text((x+22, by+5), "Gen 2", fill=YELLOW, font=F[12])
    draw.text((x+22, by+24), gen2, fill=MUTED, font=F[13])

    # Gen 3
    draw.rounded_rectangle([x+22+bw, by, x+22+bw*2, by+60], radius=8, fill=(12, 16, 30), outline=GREEN)
    draw.text((x+32+bw, by+5), "Gen 3", fill=GREEN, font=F[12])
    draw.text((x+32+bw, by+24), gen3, fill=WHITE, font=F[13])

# Bottom CTA
soft_card(draw, 90, H-95, W-180, 36, accent=ORANGE)
draw.text((120, H-88), "The path from Gen 2 to Gen 3 isn't a rewrite — it's a migration to managed services.", fill=LIGHT, font=F[16])
draw.text((1100, H-88), "AWS makes it possible.", fill=ORANGE, font=F[16])

draw_footer(draw)
save(img, "slide_challenge.png")
