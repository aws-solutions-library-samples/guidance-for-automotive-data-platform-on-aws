"""Slide 7: Modernize Every Layer with AWS"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from theme import *

img, draw = new_slide()
draw_title(draw, "MODERNIZE EVERY LAYER WITH AWS", "Fully managed services for every component of your connected vehicle platform")

layers = [
    ("Connectivity", "AWS IoT Core", "Managed MQTT · billions of messages · auto-scaling · global endpoints", "BMW: 12B requests/day", SKY),
    ("Cellular", "AWS Connectivity Services (ACS)", "Managed cellular · eSIM provisioning · carrier-agnostic · global", "Eliminate carrier lock-in", PURPLE),
    ("Streaming", "Amazon MSK", "Managed Apache Kafka · unlimited throughput · built-in replay", "Zero ops Kafka at scale", YELLOW),
    ("Processing", "Amazon Managed Flink", "Real-time analytics · Apache Flink · sub-second latency", "Real-time from day one", GREEN),
    ("Data & Analytics", "S3 Data Lake + Athena", "Serverless storage · SQL on petabytes · pay-per-query", "Toyota: PB-scale lake", GREEN),
    ("Engagement", "Amazon Connect", "Cloud contact center · AI-powered IVR · omnichannel", "Scale to millions of calls", PINK),
    ("Observability", "Amazon CloudWatch", "Unified metrics · logs · alarms · dashboards · tracing", "Single pane of glass", RED),
]

sy = 138
lh = 108
gap = 10

for i, (layer, service, detail, metric, color) in enumerate(layers):
    y = sy + i * (lh + gap)
    soft_card(draw, 90, y, W-180, lh, accent=color)

    # Layer badge
    pill(draw, 110, y+12, layer, color, F[13])

    # Service name
    draw.text((110, y+42), service, fill=ORANGE, font=F[22])

    # Detail
    draw.text((110, y+72), detail, fill=LIGHT, font=F[15])

    # Checkmarks
    checks = "✓ Managed  ✓ Pay-as-you-go  ✓ Auto-scale  ✓ Global"
    draw.text((110, y+92), checks, fill=MUTED, font=F[11])

    # Metric badge — right
    bbox = draw.textbbox((0, 0), metric, font=F[13])
    mw = bbox[2] - bbox[0] + 24
    pill(draw, W - 140 - mw, y+12, metric, GREEN, F[13])

# Proof bar
py = H - 60
soft_card(draw, 90, py, W-180, 34, accent=ORANGE)
draw.text((120, py+7), "PROVEN:", fill=ORANGE, font=F[15])
draw.text((210, py+7), "BMW 20M cars, 1,300 microservices migrated  ·  WirelessCar 10M→100M vehicles  ·  Honda serverless in 4 regions  ·  Toyota 8M+ customers", fill=LIGHT, font=F[13])

draw_footer(draw)
save(img, "slide7_modernize.png")
