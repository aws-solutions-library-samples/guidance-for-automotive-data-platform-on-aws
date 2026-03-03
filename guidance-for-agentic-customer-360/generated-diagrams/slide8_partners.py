"""Slide 8: Accelerate with AWS Automotive Partners"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from theme import *

img, draw = new_slide()
draw_title(draw, "ACCELERATE WITH AWS AUTOMOTIVE PARTNERS", "Pre-built solutions on AWS — deploy in weeks, not years")

# Column headers
headers = [("Layer", LIGHT, 90), ("AWS Foundation", ORANGE, 500), ("Partner Solutions", PURPLE, 960)]
hy = 135
for label, color, x in headers:
    draw.text((x+20, hy), label, fill=color, font=F[16])
# Header underline
draw.line([(90, hy+26), (W-90, hy+26)], fill=BORDER, width=1)

layers = [
    ("Connectivity", SKY, "AWS IoT Core", ["WirelessCar", "Sibros", "Airbiquity"], "Turnkey CV platforms"),
    ("Cellular", PURPLE, "AWS Connectivity Services", ["T-Mobile", "Vodafone", "KORE"], "Global connectivity & SIM mgmt"),
    ("Streaming", YELLOW, "Amazon MSK", ["Confluent", "Redpanda", "Striim"], "Enterprise streaming on AWS"),
    ("Processing", GREEN, "Amazon Managed Flink", ["Databricks", "Decodable"], "Advanced real-time analytics"),
    ("Data & Analytics", GREEN, "S3 + Athena + SageMaker", ["Databricks", "Snowflake", "Teradata"], "Enterprise data platforms"),
    ("Engagement", PINK, "Amazon Connect", ["Salesforce", "Genesys", "Zendesk"], "CRM & omnichannel"),
    ("Observability", RED, "Amazon CloudWatch", ["Datadog", "Splunk", "Dynatrace"], "Enterprise monitoring & APM"),
]

sy = 175
rh = 100
gap = 12

for i, (layer, color, aws_svc, partners, partner_desc) in enumerate(layers):
    y = sy + i * (rh + gap)

    # Row background
    soft_card(draw, 90, y, W-180, rh)

    # Layer column
    draw.ellipse([110, y+rh//2-8, 126, y+rh//2+8], fill=color)
    draw.text((136, y+rh//2-12), layer, fill=WHITE, font=F[18])

    # AWS column
    draw.text((520, y+16), aws_svc, fill=ORANGE, font=F[18])
    draw.text((520, y+44), "✓ Managed  ✓ Pay-as-you-go  ✓ Auto-scale", fill=MUTED, font=F[13])

    # Partners column
    px = 980
    for partner in partners:
        pw = pill(draw, px, y+12, partner, PURPLE, F[13])
        px += pw + 8
    draw.text((980, y+44), partner_desc, fill=LIGHT, font=F[14])

    # Marketplace badge
    pill(draw, W-280, y+rh-30, "☁ AWS Marketplace", SKY, F[11])

# CTA bar
cy = H - 58
soft_card(draw, 90, cy, W-180, 32, accent=PURPLE)
draw.text((120, cy+6), "AWS AUTOMOTIVE COMPETENCY", fill=PURPLE, font=F[16])
draw.text((440, cy+7), "Validated partners with proven automotive expertise  ·  ", fill=LIGHT, font=F[14])
draw.text((920, cy+7), "aws.amazon.com/automotive/partners", fill=SKY, font=F[14])

draw_footer(draw)
save(img, "slide8_partners.png")
