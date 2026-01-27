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

[View Platform Foundation Documentation →](platform-foundation/PLATFORM_README.md)

---

### 🎯 Guidance: Agentic Customer 360
**Path**: [`guidance-for-agentic-customer-360/`](guidance-for-agentic-customer-360/)

**Status**: ✅ Production Ready

AI-powered Customer 360 analytics platform with Amazon Bedrock agents:
- Real-time customer health scoring (0-100 scale)
- ML-powered churn prediction with revenue-at-risk calculations
- Customer Lifetime Value (CLV) modeling across 5 revenue streams
- Amazon Bedrock agents for proactive customer intervention
- Amazon Quick Suite dashboards for executive insights
- 50+ production-ready Athena queries

**Use this when**: Building customer analytics and retention systems

[View Customer 360 Documentation →](guidance-for-agentic-customer-360/README.md)

**Quick Start**:
```bash
cd guidance-for-agentic-customer-360
make install bootstrap
make deploy-all
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
        │  Future: Connected Mobility           │
        │  - Vehicle telemetry analytics        │
        │  - Predictive maintenance             │
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
- Track customer health across lifecycle
- Predict and prevent churn
- Optimize customer lifetime value
- AI-powered intervention recommendations

### Vehicle Data & IoT
→ Use **Platform Foundation** + Custom Project
- Ingest vehicle telemetry
- Predictive maintenance models
- Fleet analytics

### Sales & Marketing
→ Use **Platform Foundation** + **Shared Data Sources**
- Sales forecasting
- Marketing campaign optimization
- Customer segmentation

## Documentation

- [Platform Foundation Guide](platform-foundation/PLATFORM_README.md)
- [Customer 360 Deployment Guide](guidance-for-agentic-customer-360/docs/DEPLOYMENT.md)
- [Data Model Specification](guidance-for-agentic-customer-360/docs/DATA_MODEL_SPEC.md)
- [Bedrock Agents Guide](guidance-for-agentic-customer-360/docs/BEDROCK_AGENTS.md)
- [Quick Suite Security](guidance-for-agentic-customer-360/docs/QUICK_SUITE_SECURITY.md)

## Cost Estimates

### Customer 360 Platform
- **Base**: $184-355/month (S3, Glue, Athena, Quick Suite)
- **With AI**: $434-905/month (includes Bedrock agents)

### Platform Foundation
- **Base**: $200-500/month (VPC, NAT Gateway, SageMaker domain)
- **Per User**: +$18/month (SageMaker Unified Studio)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT-0 License. See [LICENSE](LICENSE) file.

## Support

For issues and questions:
- Customer 360: See [guidance-for-agentic-customer-360/README.md](guidance-for-agentic-customer-360/README.md)
- Platform Foundation: See [platform-foundation/PLATFORM_README.md](platform-foundation/PLATFORM_README.md)

---

**Note**: The Platform Foundation provides the base infrastructure. The Guidance projects are self-contained and can be deployed independently or on top of the foundation.
