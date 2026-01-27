# Automotive Data Platform on AWS

## Overview

This repository provides AWS guidance and reference implementations for building comprehensive automotive data platforms. It includes foundational infrastructure and specialized guidance for specific use cases.

## Repository Structure

### 🏗️ Platform Foundation
**Path**: [`platform-foundation/`](platform-foundation/)

Base infrastructure for automotive data platforms using Amazon SageMaker Unified Studio:
- Unified data workspace for data engineers and ML engineers
- VPC networking with private subnets and service endpoints
- IAM Identity Center integration for team collaboration
- DataZone domain for data governance and cataloging
- Blueprint enablement for common automotive patterns

**Use this when**: Setting up a new automotive data platform from scratch

[View Platform Foundation Documentation →](platform-foundation/README.md)

---

### 🎯 Guidance: Agentic Customer 360
**Path**: [`guidance-for-agentic-customer-360/`](guidance-for-agentic-customer-360/)

**Status**: ✅ Production Ready

AI-powered Customer 360 analytics platform demonstrating declining business metrics and root cause analysis:
- **Synthetic data** with realistic declining trends (NPS 52→42, Health 65→56)
- **Battery issue analysis** (15%→40% over 12 months) for root cause demonstration
- **QuickSight dashboards** with 8 pre-built datasets and automated deployment
- **Bedrock Agent** with Aurora pgvector knowledge base for natural language queries
- **500K customers** with 1.4M interactions and 900K service records
- **Interactive Makefile** deployment with AWS profile/region selection

**Use this when**: Building customer analytics platforms with AI-powered insights

[View Customer 360 Documentation →](guidance-for-agentic-customer-360/README.md)

**Quick Start**:
```bash
cd guidance-for-agentic-customer-360
make deploy
# Select profile, region, and deployment option from interactive menu
```

---

### 🔧 Guidance: Predictive Maintenance
**Path**: [`guidance-for-predictive-maintenance/`](guidance-for-predictive-maintenance/)

**Status**: ✅ Production Ready

ML-powered predictive maintenance for vehicle tires using anomaly detection:
- Real-time tire pressure and temperature monitoring
- Random Cut Forest model for anomaly detection
- Automated alert system for slow leaks and failures
- REST API for real-time inference
- Batch processing pipeline for daily analysis
- Step Functions orchestration for ML workflows

**Use this when**: Building predictive maintenance and vehicle health monitoring

[View Predictive Maintenance Documentation →](guidance-for-predictive-maintenance/README.md)

**Quick Start**:
```bash
cd guidance-for-predictive-maintenance
make deploy
```

---

### 📊 Shared Data Sources
**Path**: [`datasource/`](datasource/)

Synthetic data generators for automotive use cases:
- CRM data (customers, contacts, accounts)
- Vehicle telemetry and service records
- Sales and transaction history
- Configurable data profiles (small/medium/large)

**Use this when**: Testing and development without production data

[View Data Source Documentation →](datasource/README.md)

---

## Getting Started

### For Customer 360 Analytics
If you want to deploy the Customer 360 platform:

```bash
cd guidance-for-agentic-customer-360
make help
```

### For Base Platform Infrastructure
If you want to set up the foundational SageMaker Unified Studio environment:

```bash
cd platform-foundation
./deployment/deploy-complete-platform.sh
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Platform Foundation (SageMaker Unified Studio)                 │
│  - Unified data workspace                                       │
│  - VPC networking & security                                    │
│  - IAM Identity Center                                          │
│  - DataZone governance                                          │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ Hosts Projects
                            ▼
        ┌───────────────────────────────────────┐
        │  Guidance: Agentic Customer 360       │
        │  - Customer health scoring            │
        │  - Churn prediction                   │
        │  - Bedrock AI agents                  │
        │  - Quick Suite dashboards             │
        └───────────────────────────────────────┘
                            │
        ┌───────────────────────────────────────┐
        │  Guidance: Predictive Maintenance     │
        │  - Tire anomaly detection             │
        │  - ML-powered alerts                  │
        │  - Real-time inference API            │
        │  - Batch processing pipeline          │
        └───────────────────────────────────────┘
                            │
        ┌───────────────────────────────────────┐
        │  Future: Connected Mobility           │
        │  - Vehicle telemetry analytics        │
        │  - Fleet management                   │
        └───────────────────────────────────────┘
                            │
        ┌───────────────────────────────────────┐
        │  Future: Supply Chain Optimization    │
        │  - Inventory forecasting              │
        │  - Demand planning                    │
        └───────────────────────────────────────┘
```

## Use Cases

### Customer Analytics & Retention
→ Use **Guidance: Agentic Customer 360**
- Analyze declining customer metrics and trends
- Root cause analysis with AI-powered insights
- Interactive dashboards with QuickSight
- Natural language queries with Bedrock Agent
- Demonstrate data-driven decision making

### Predictive Maintenance & Vehicle Health
→ Use **Guidance: Predictive Maintenance**
- Monitor tire pressure and temperature
- Detect slow leaks and anomalies
- Real-time alerts for failures
- ML-powered anomaly detection

### Vehicle Data & IoT
→ Use **Platform Foundation** + Custom Project
- Ingest vehicle telemetry
- Fleet analytics
- Connected vehicle insights

### Sales & Marketing
→ Use **Platform Foundation** + **Shared Data Sources**
- Sales forecasting
- Marketing campaign optimization
- Customer segmentation

## Documentation

- [Platform Foundation Guide](platform-foundation/README.md)
- [Customer 360 Deployment Guide](guidance-for-agentic-customer-360/docs/DEPLOYMENT.md)
- [Predictive Maintenance Deployment Guide](guidance-for-predictive-maintenance/docs/DEPLOYMENT.md)
- [Customer 360 + Predictive Maintenance Integration](guidance-for-predictive-maintenance/docs/CUSTOMER_360_INTEGRATION.md)
- [Data Model Specification](guidance-for-agentic-customer-360/docs/DATA_MODEL_SPEC.md)
- [Bedrock Agents Guide](guidance-for-agentic-customer-360/docs/BEDROCK_AGENTS.md)
- [Quick Suite Security](guidance-for-agentic-customer-360/docs/QUICK_SUITE_SECURITY.md)

## Cost Estimates

### Customer 360 Platform
- **Data Layer**: ~$20/month (S3, Glue, Athena)
- **Analytics**: $24+/user/month (QuickSight Enterprise)
- **AI Layer**: ~$70/month (Aurora Serverless, Bedrock)
- **Total**: ~$114/month + QuickSight users

### Predictive Maintenance
- **Standalone**: $118-245/month (SageMaker, Step Functions, Glue, API Gateway)
- **With Platform**: $113-235/month (shared infrastructure)

### Platform Foundation
- **Base**: $50-250/month (VPC, NAT Gateway, SageMaker domain)
- **Per User**: +$18/month (SageMaker Unified Studio)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT-0 License. See [LICENSE](LICENSE) file.

## Support

For issues and questions:
- Customer 360: See [guidance-for-agentic-customer-360/README.md](guidance-for-agentic-customer-360/README.md)
- Platform Foundation: See [platform-foundation/README.md](platform-foundation/README.md)

---

**Note**: The Platform Foundation provides the base infrastructure. The Guidance projects are self-contained and can be deployed independently or on top of the foundation.
