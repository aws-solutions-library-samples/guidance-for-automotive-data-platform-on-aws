# Platform Foundation - Automotive Data Platform

## Overview

The Platform Foundation provides the base infrastructure for automotive data platforms using **Amazon SageMaker Unified Studio**. It creates a unified workspace where data engineers, ML engineers, and business analysts can collaborate on automotive use cases.

## What is SageMaker Unified Studio?

Amazon SageMaker Unified Studio is an integrated development environment that brings together:
- **Data Engineering**: Glue, Athena, Redshift for data processing
- **ML Engineering**: SageMaker for model training and deployment
- **Analytics**: Quick Suite for dashboards and insights
- **Governance**: DataZone for data cataloging and access control
- **Collaboration**: Shared projects and notebooks

## Automotive Data Platform Alignment

### Core Capabilities for Automotive

**1. Multi-Source Data Integration**
- Vehicle telemetry (IoT, CAN bus data)
- Customer data (CRM, service records)
- Sales and inventory systems
- External data (weather, traffic, maps)

**2. Unified Data Catalog**
- DataZone domain for automotive data assets
- Searchable catalog of datasets
- Data lineage tracking
- Access governance

**3. Collaborative Workspaces**
- Projects for specific use cases (Customer 360, Predictive Maintenance, etc.)
- Shared notebooks and queries
- Team-based access control

**4. ML & Analytics Pipeline**
- End-to-end ML workflows
- Real-time and batch processing
- Model deployment and monitoring
- Dashboard creation and sharing

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  SageMaker Unified Studio Domain                                │
│  ├── DataZone Catalog (Automotive Data Assets)                  │
│  ├── Projects (Customer 360, Predictive Maintenance, etc.)      │
│  └── Blueprints (Common Patterns)                               │
└─────────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │                                       │
        ▼                                       ▼
┌──────────────────┐                  ┌──────────────────┐
│  Data Sources    │                  │  Compute         │
│  - S3 Data Lake  │                  │  - Glue Jobs     │
│  - RDS/Aurora    │                  │  - SageMaker     │
│  - IoT Core      │                  │  - Athena        │
│  - Redshift      │                  │  - EMR           │
└──────────────────┘                  └──────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │  Networking      │
                  │  - VPC           │
                  │  - Private       │
                  │    Subnets       │
                  │  - VPC Endpoints │
                  └──────────────────┘
```

## Components

### 1. Networking (`deployment/sagemaker_us_guidance_network_setup.yaml`)
- VPC with 3 private subnets across AZs
- NAT Gateway for outbound connectivity
- VPC endpoints for AWS services (S3, Glue, SageMaker, Athena, etc.)
- Security groups for controlled access

### 2. DataZone Domain (`cloudformation/datazone-domain.yaml`)
- Unified data catalog
- Project management
- Data governance and access control
- Blueprint enablement

### 3. IAM Identity Center Integration (`deployment/setup-sso-permissions.sh`)
- Centralized user management
- SSO for SageMaker Unified Studio
- Role-based access control

### 4. Blueprints (`cloudformation/enable-all-blueprints.yaml`)
- Pre-configured patterns for common use cases
- Automotive-specific templates
- Accelerated project setup

## Deployment

### Prerequisites
- AWS Account with admin access
- IAM Identity Center enabled
- AWS CLI configured

### Quick Start

```bash
# Deploy complete platform
./deployment/deploy-complete-platform.sh

# Or step-by-step
./deployment/deploy-base-platform.sh        # VPC and networking
./deployment/deploy-datazone-domain.sh      # DataZone domain
./deployment/enable-blueprints-with-sso.sh  # Enable blueprints
```

### Configuration

Edit `deployment/stack-outputs.env` to customize:
- VPC CIDR ranges
- Subnet configurations
- Domain name
- Region

## Automotive Use Cases

### 1. Customer 360 Analytics
**Project**: `guidance-for-agentic-customer-360`
- Ingest CRM and service data
- Calculate customer health scores
- Predict churn and lifetime value
- Deploy Bedrock agents for interventions

### 2. Predictive Maintenance
**Setup**: Create new project in SageMaker Unified Studio
- Ingest vehicle telemetry
- Train failure prediction models
- Deploy real-time inference endpoints
- Alert service teams

### 3. Connected Vehicle Analytics
**Setup**: Create new project
- Stream IoT data from vehicles
- Process with Glue/Kinesis
- Store in S3 data lake
- Analyze with Athena/Quick Suite

### 4. Supply Chain Optimization
**Setup**: Create new project
- Integrate inventory systems
- Forecast demand
- Optimize parts distribution
- Track supplier performance

## Integration with Guidance Projects

The Platform Foundation provides the base infrastructure. Guidance projects like **Customer 360** can:

**Option A: Deploy Independently**
- Use guidance project's own CDK stacks
- Self-contained deployment
- No dependency on Platform Foundation

**Option B: Deploy on Platform Foundation**
- Create project in SageMaker Unified Studio
- Use DataZone catalog for data discovery
- Leverage shared VPC and networking
- Collaborate with other teams

## Cost Estimate

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| VPC & Networking | $50-100 | NAT Gateway, VPC endpoints |
| SageMaker Domain | $0 | No charge for domain |
| SageMaker Studio | $18/user | Per active user |
| DataZone | $0-50 | Depends on usage |
| **Total** | **$50-250/month** | Base + 5 users |

**Note**: Actual costs depend on:
- Number of active users
- Data processing volume
- ML training workloads
- Storage requirements

## Monitoring

### CloudWatch Dashboards
- VPC flow logs
- NAT Gateway metrics
- SageMaker usage
- DataZone activity

### Cost Tracking
```bash
# View costs by service
aws ce get-cost-and-usage \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=SERVICE
```

## Maintenance

### Regular Tasks
- Review IAM policies and permissions
- Update VPC security groups
- Monitor NAT Gateway usage
- Review DataZone catalog

### Cleanup
```bash
# Remove all resources
./deployment/cleanup-all.sh
```

## Troubleshooting

### SageMaker Domain Creation Fails
- Check IAM Identity Center is enabled
- Verify VPC and subnets exist
- Ensure proper IAM permissions

### DataZone Domain Issues
- Verify SSO configuration
- Check domain owner permissions
- Review CloudFormation stack events

### Network Connectivity
- Verify NAT Gateway is running
- Check VPC endpoint configurations
- Review security group rules

## Next Steps

1. **Deploy Platform Foundation** (this)
2. **Create First Project** (e.g., Customer 360)
3. **Ingest Data** to S3 data lake
4. **Catalog Data** in DataZone
5. **Build Analytics** with Athena/Quick Suite
6. **Train Models** with SageMaker

## References

- [SageMaker Unified Studio Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/unified-studio.html)
- [DataZone Documentation](https://docs.aws.amazon.com/datazone/latest/userguide/)
- [VPC Best Practices](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-best-practices.html)

---

**Related Projects**:
- [Guidance: Agentic Customer 360](../guidance-for-agentic-customer-360/) - Customer analytics platform
- [Shared Data Sources](../datasource/) - Synthetic data generators
