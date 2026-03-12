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

ML-powered predictive maintenance for tire health monitoring and failure prediction:
- **Random Cut Forest** anomaly detection for tire pressure and temperature
- **7-14 day advance warning** of tire failures and slow leaks
- **Dual approach**: ML-based and filter-based prediction algorithms
- **Real-time inference API** with API Gateway and Lambda
- **Batch processing** with Step Functions orchestration
- **Automated alerts** integrated with maintenance scheduling systems
- **ETL pipeline** with AWS Glue for data transformation

**Use this when**: Building predictive maintenance systems for vehicle health monitoring

[View Predictive Maintenance Documentation →](guidance-for-predictive-maintenance/README.md)

**Quick Start**:
```bash
cd guidance-for-predictive-maintenance
make install
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

### Option 1: Customer 360 Analytics (Standalone)
Deploy the Customer 360 platform independently - no other infrastructure needed:

```bash
cd guidance-for-agentic-customer-360
make deploy
```

**What you get**: Complete analytics platform with data lake, QuickSight dashboards, and Bedrock AI agent.

---

### Option 2: Platform Foundation (Optional)
Set up the foundational SageMaker Unified Studio environment for team collaboration:

```bash
cd platform-foundation
./deployment/deploy-complete-platform.sh
```

**What you get**: Shared workspace for data engineers and ML engineers with DataZone governance.

**Note**: Platform Foundation is NOT required for Customer 360. Deploy it only if you need a shared team workspace.

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
- Predict tire failures 7-14 days in advance
- Monitor tire pressure and temperature anomalies
- Dual ML and filter-based detection algorithms
- Real-time and batch inference pipelines
- Automated maintenance alerts and scheduling

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
- **ML Pipeline**: ~$150-300/month (SageMaker training, batch transform, Glue ETL)
- **Real-time API**: ~$50-100/month (API Gateway, Lambda, Step Functions)
- **Data Storage**: ~$20-50/month (S3, Glue catalog)
- **Total**: ~$220-450/month (depending on data volume and inference frequency)

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

## Notices

*Customers are responsible for making their own independent assessment of the information in this Guidance. This Guidance: (a) is for informational purposes only, (b) represents AWS current product offerings and practices, which are subject to change without notice, and (c) does not create any commitments or assurances from AWS and its affiliates, suppliers or licensors. AWS products or services are provided "as is" without warranties, representations, or conditions of any kind, whether express or implied. AWS responsibilities and liabilities to its customers are controlled by AWS agreements, and this Guidance is not part of, nor does it modify, any agreement between AWS and its customers.*
