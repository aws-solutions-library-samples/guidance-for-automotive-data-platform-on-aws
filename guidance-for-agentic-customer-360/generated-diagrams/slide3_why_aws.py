"""Slide 3: Why AWS for Automotive — logos + one-liners"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from theme import *

img, draw = new_slide()
draw_title(draw, "WHY AWS FOR AUTOMOTIVE", "Making it easier to innovate, modernize, and scale")

# Stat banner
by = 145
soft_card(draw, 90, by, W-180, 80, accent=ORANGE)
draw.text((120, by+10), "Leading OEMs Trust AWS to Power", fill=WHITE, font=F[28])
draw.text((120, by+44), "Millions of Connected Vehicles Globally", fill=ORANGE, font=F[24])
# Badges
pill(draw, W-480, by+12, "Frost & Sullivan 2022 #1", ORANGE, F[13])
pill(draw, W-480, by+44, "BMW · Honda · Toyota · Rivian & more", SKY, F[13])

# Four categories
categories = [
    ("Connected Vehicle", SKY, [
        ("BMW Group", "20M connected cars · 12B daily requests"),
        ("Toyota", "8M+ customers · petabyte-scale data lake"),
        ("WirelessCar", "10M+ vehicles · 100+ countries"),
        ("Honda", "Serverless platform for millions of cars"),
    ]),
    ("Software Defined Vehicle", GREEN, [
        ("Ford", "Transportation Mobility Cloud on AWS"),
        ("HARMAN", "SDV OTA & cybersecurity on AWS"),
        ("DENSO", "ADAS ML development on AWS"),
        ("Volkswagen Group", "Industrial Cloud across 120+ plants"),
    ]),
    ("Digital Customer Experience", PINK, [
        ("Cox Automotive", "2.3B interactions/yr · 17 AI agents"),
        ("Lucid", "Cloud-rendered 3D car buying experience"),
        ("TrueCar", "All-in on AWS · real-time marketplace"),
        ("Audi", "Cloud configurator & smart store · 60-70% savings"),
    ]),
    ("Autonomous Mobility", PURPLE, [
        ("Zoox", "Hundreds of PBs · driverless robotaxi on AWS"),
        ("Aurora", "Trillions of data points · 12M sims/day"),
        ("Torc Robotics", "Daimler Truck's self-driving fleet on AWS"),
        ("AUMOVIO", "Gen AI-powered AV dev with Bedrock"),
    ]),
]

col_w = (W - 220) // 4
start_y = 250
for ci, (cat_name, color, logos) in enumerate(categories):
    x = 90 + ci * (col_w + 14)

    # Category header
    soft_card(draw, x, start_y, col_w, 36, accent=color)
    draw.text((x+16, start_y+8), cat_name, fill=color, font=F[15])

    # Logo items
    for li, (name, desc) in enumerate(logos):
        iy = start_y + 50 + li * 170
        soft_card(draw, x, iy, col_w, 155)

        # Accent dot
        draw.ellipse([x+16, iy+18, x+24, iy+26], fill=color)
        draw.text((x+32, iy+14), name, fill=WHITE, font=F[18])

        # Description - wrap
        words = desc.split()
        lines = []
        line = ""
        for w in words:
            test = f"{line} {w}".strip()
            bbox = draw.textbbox((0, 0), test, font=F[13])
            if bbox[2] - bbox[0] > col_w - 50:
                lines.append(line)
                line = w
            else:
                line = test
        if line:
            lines.append(line)
        for j, l in enumerate(lines):
            draw.text((x+32, iy+42 + j*18), l, fill=LIGHT, font=F[13])

draw_footer(draw)
save(img, "slide3_why_aws.png")
