"""Slide 6: Anatomy of a Connected Vehicle Platform"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from theme import *

img, draw = new_slide()
draw_title(draw, "ANATOMY OF A CONNECTED VEHICLE PLATFORM", "Understanding the layers of your current stack")

layers = [
    ("Connectivity", "Vehicle-to-cloud communication", SKY,
     ["MQTT Brokers", "Device Provisioning", "Certificate Mgmt", "Protocol Translation"],
     "Capacity limits · manual scaling · single region"),
    ("Cellular & Network", "Cellular connectivity for fleet", PURPLE,
     ["SIM Management", "APN Configuration", "Carrier Contracts", "Roaming"],
     "Vendor lock-in · expensive licensing · complex carrier mgmt"),
    ("Ingestion & Streaming", "Real-time data pipelines", YELLOW,
     ["Message Queuing", "Event Streaming", "Telemetry Ingestion", "Stream Processing"],
     "Fragile pipelines · no replay · batch-only insights"),
    ("Data & Analytics", "Storage, query, and insights", GREEN,
     ["Data Warehouse", "ETL Pipelines", "SQL Analytics", "ML / Predictions"],
     "Fixed capacity · overnight batch jobs · siloed data"),
    ("Customer Engagement", "Call center & notifications", PINK,
     ["IVR Systems", "Call Routing", "CRM Integration", "Push Notifications"],
     "Hardware-dependent · hard to scale · poor CX"),
    ("Observability", "Monitoring & alerting", RED,
     ["Log Aggregation", "Dashboards", "Alerting", "Distributed Tracing"],
     "Reactive · siloed dashboards · no unified view"),
]

sy = 140
lh = 130
gap = 14

for i, (name, desc, color, components, pain) in enumerate(layers):
    y = sy + i * (lh + gap)
    soft_card(draw, 90, y, W-180, lh, accent=color)

    # Layer number circle
    cx, cy_ = 125, y + lh//2
    draw.ellipse([cx-16, cy_-16, cx+16, cy_+16], fill=CARD, outline=color)
    draw.text((cx-6, cy_-10), str(i+1), fill=color, font=F[16])

    # Name + desc
    draw.text((160, y+14), name, fill=WHITE, font=F[22])
    draw.text((160, y+42), desc, fill=MUTED, font=F[15])

    # Component pills
    px = 160
    py = y + 75
    for comp in components:
        pw = pill(draw, px, py, comp, color, F[13])
        px += pw + 8

    # Pain point — right aligned
    pain_text = "⚠ " + pain
    bbox = draw.textbbox((0, 0), pain_text, font=F[13])
    ptw = bbox[2] - bbox[0]
    draw.text((W - 130 - ptw, y + 18), pain_text, fill=RED, font=F[13])

# Bottom hook
hy = H - 55
soft_card(draw, 90, hy, W-180, 30)
draw.text((120, hy+5), "Each layer = infrastructure you build, maintain, patch, and scale —", fill=LIGHT, font=F[16])
draw.text((870, hy+5), "what if you didn't have to?", fill=ORANGE, font=F[16])

draw_footer(draw)
save(img, "slide6_anatomy.png")
