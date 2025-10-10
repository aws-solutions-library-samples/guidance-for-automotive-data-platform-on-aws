# Automotive Data Platform Architecture

## Overview

This platform provides a flexible foundation for automotive data and ML workloads using Amazon DataZone. The architecture supports both single-domain and multi-domain deployment strategies.

## Architecture Options

### Option A: Single Domain (Current Implementation)

**Best for**: Unified automotive data platform with cross-functional collaboration

```
DataZone Domain: automotive-data-platform
Portal: https://d-{domain-id}.datazone.us-east-1.amazonaws.com
│
├── Business Area: Vehicle Intelligence
│   ├── Producer: vehicle-telemetry-ingestion
│   ├── Consumer: tire-prediction-ml
│   └── Consumer: battery-health-ml
│
├── Business Area: Supply Chain
│   ├── Producer: supply-chain-data-ingestion
│   └── Consumer: demand-forecasting
│
├── Business Area: Warranty & PLM
│   ├── Producer: warranty-plm-ingestion
│   └── Consumer: claim-prediction
│
└── Business Area: Manufacturing
    ├── Producer: manufacturing-data-ingestion
    └── Consumer: production-optimization
```

**Advantages:**
- ✅ Single portal for all users
- ✅ Unified data catalog and discovery
- ✅ Easier cross-domain data sharing
- ✅ Simpler governance model
- ✅ Lower operational overhead

**Use When:**
- Teams need to collaborate across business areas
- Data discovery across domains is important
- Unified governance is acceptable
- Cost optimization is priority

### Option B: Multi-Domain (Enterprise Architecture)

**Best for**: Large enterprises with strict data boundaries and compliance requirements

```
Central AWS Account: Automotive Data Platform
│
├── Domain 1: automotive-vehicle-intelligence
│   Portal: https://d-abc123.datazone.us-east-1.amazonaws.com
│   ├── Data Products: Vehicle telemetry, diagnostics, performance
│   ├── Storage: S3 Data Lake (Iceberg)
│   ├── Projects: tire-prediction, battery-health, predictive-maintenance
│   └── Users: ML Engineers, Data Scientists, Fleet Operations
│
├── Domain 2: automotive-supply-chain
│   Portal: https://d-def456.datazone.us-east-1.amazonaws.com
│   ├── Data Products: Parts inventory, supplier data, logistics
│   ├── Storage: Redshift Serverless + S3
│   ├── Projects: demand-forecasting, supplier-analytics, inventory-optimization
│   └── Users: Supply Chain Analysts, Procurement, Operations
│
├── Domain 3: automotive-warranty-plm
│   Portal: https://d-ghi789.datazone.us-east-1.amazonaws.com
│   ├── Data Products: Warranty claims, recall data, PLM integration
│   ├── Storage: Redshift Serverless + S3
│   ├── Projects: claim-prediction, recall-impact-analysis, defect-tracking
│   └── Users: Quality Engineers, Legal, Compliance, Customer Service
│
├── Domain 4: automotive-sales-marketing
│   Portal: https://d-jkl012.datazone.us-east-1.amazonaws.com
│   ├── Data Products: Sales data, customer data, market trends
│   ├── Storage: Redshift Serverless + S3
│   ├── Projects: sales-forecasting, customer-segmentation, pricing-optimization
│   └── Users: Sales Analysts, Marketing, Finance
│
└── Domain 5: automotive-manufacturing
    Portal: https://d-mno345.datazone.us-east-1.amazonaws.com
    ├── Data Products: Production data, quality metrics, IoT sensors
    ├── Storage: Redshift Serverless + S3
    ├── Projects: production-optimization, quality-prediction, downtime-analysis
    └── Users: Manufacturing Engineers, Plant Managers, Quality Assurance
```

**Advantages:**
- ✅ Strict data isolation per business domain
- ✅ Independent governance and compliance
- ✅ Separate cost allocation
- ✅ Domain-specific access controls
- ✅ Scalable for large enterprises

**Use When:**
- Regulatory requirements demand data isolation
- Different compliance needs per domain (e.g., GDPR, ITAR)
- Separate business units with independent budgets
- Need for domain-specific governance policies

## Data Storage Strategy by Domain

### Vehicle Intelligence Domain
- **Primary**: S3 Data Lake (Iceberg tables)
- **Why**: High-volume streaming, ML training, time-series
- **Size**: 10+ TB, growing daily
- **Query**: Athena, Spark, SageMaker

### Supply Chain Domain
- **Primary**: Redshift Serverless
- **Secondary**: S3 for raw data
- **Why**: Complex joins, supplier relationships, inventory aggregations
- **Size**: 1-5 TB
- **Query**: SQL analytics, QuickSight dashboards

### Warranty & PLM Domain
- **Primary**: Redshift Serverless
- **Secondary**: S3 for document storage
- **Why**: Relational data, regulatory reporting, complex queries
- **Size**: 500 GB - 2 TB
- **Query**: SQL analytics, compliance reports

### Manufacturing Domain
- **Primary**: Redshift Serverless
- **Secondary**: S3 for IoT sensor data
- **Why**: Production metrics, quality data, real-time dashboards
- **Size**: 2-10 TB
- **Query**: SQL analytics, real-time BI

### Sales & Marketing Domain
- **Primary**: Redshift Serverless
- **Secondary**: S3 for customer data
- **Why**: CRM integration, sales analytics, forecasting
- **Size**: 500 GB - 2 TB
- **Query**: SQL analytics, QuickSight, Tableau

## Data Producer Patterns

### Pattern 1: Streaming Producer (Vehicle Telemetry)

```
IoT Core (vehicles)
    ↓ MQTT
MSK (Kafka)
    ↓ Stream
Flink Processor
    ├→ Transform to tire telemetry
    ├→ Transform to battery telemetry
    └→ Transform to diagnostics
        ↓ Write
S3 Data Lake (Iceberg)
    ↓ Register
Glue Data Catalog
    ↓ Publish
DataZone Data Product
    ↓ Subscribe
Consumer Projects (ML models)
```

**Producer Project**: `vehicle-telemetry-producer`
**Data Products**: 
- `tire_telemetry` (real-time, partitioned by date)
- `battery_telemetry` (real-time, partitioned by date)
- `engine_diagnostics` (real-time, partitioned by date)

### Pattern 2: Batch ETL Producer (Supply Chain)

```
ERP System (SAP)
    ↓ Daily Extract
S3 Landing Zone
    ↓ Glue ETL
Redshift Serverless
    ↓ Register
Glue Data Catalog
    ↓ Publish
DataZone Data Product
    ↓ Subscribe
Consumer Projects (forecasting)
```

**Producer Project**: `supply-chain-data-producer`
**Data Products**:
- `parts_inventory` (daily refresh)
- `supplier_performance` (weekly refresh)
- `procurement_orders` (real-time)

### Pattern 3: API Producer (Warranty/PLM)

```
PLM System API
    ↓ Lambda Extractor
S3 Raw Data
    ↓ Glue ETL
Redshift Serverless
    ↓ Register
Glue Data Catalog
    ↓ Publish
DataZone Data Product
    ↓ Subscribe
Consumer Projects (claim prediction)
```

**Producer Project**: `warranty-plm-producer`
**Data Products**:
- `warranty_claims` (daily refresh)
- `recall_campaigns` (event-driven)
- `defect_reports` (real-time)

### Pattern 4: IoT Sensor Producer (Manufacturing)

```
Factory IoT Sensors
    ↓ IoT Core
Kinesis Data Streams
    ↓ Firehose
S3 + Redshift Serverless
    ↓ Register
Glue Data Catalog
    ↓ Publish
DataZone Data Product
    ↓ Subscribe
Consumer Projects (quality prediction)
```

**Producer Project**: `manufacturing-data-producer`
**Data Products**:
- `production_metrics` (real-time)
- `quality_measurements` (batch)
- `equipment_telemetry` (streaming)

## Cross-Domain Data Flow Example

**Use Case**: Tire Prediction ML needs data from multiple domains

```
Vehicle Intelligence Domain
    └── tire_telemetry (producer)
            ↓ Published
        DataZone Catalog
            ↓ Cross-domain subscription request
        Approval Workflow
            ↓ Approved
Supply Chain Domain
    └── tire_parts_inventory (producer)
            ↓ Published
        DataZone Catalog
            ↓ Cross-domain subscription
Warranty Domain
    └── tire_warranty_claims (producer)
            ↓ Published
        DataZone Catalog
            ↓ All subscribed to
Consumer Project: tire-prediction-ml
    └── Trains model with all 3 data sources
```

## Implementation Recommendation

### Phase 1: Start with Single Domain (Current)
- Deploy one domain: `automotive-data-platform`
- Create producer project: `vehicle-telemetry-producer`
- Create consumer project: `tire-prediction-ml`
- Validate end-to-end workflow

### Phase 2: Add Business Areas as Projects
- Add supply chain projects
- Add warranty/PLM projects
- Keep in same domain for simplicity

### Phase 3: Split into Multiple Domains (If Needed)
- Migrate to multi-domain when:
  - Compliance requires isolation
  - Teams need independent governance
  - Scale demands separation
- Use DataZone cross-domain sharing

## Decision Matrix

| Requirement | Single Domain | Multi-Domain |
|-------------|---------------|--------------|
| Unified data discovery | ✅ Better | ⚠️ Requires cross-domain search |
| Strict data isolation | ⚠️ Project-level only | ✅ Domain-level |
| User experience | ✅ One portal | ❌ Multiple portals |
| Governance complexity | ✅ Simpler | ⚠️ More complex |
| Cross-domain sharing | ✅ Native | ⚠️ Requires approval workflow |
| Cost allocation | ⚠️ Project-level | ✅ Domain-level |
| Compliance boundaries | ⚠️ Limited | ✅ Strong |

## Current Status

**Deployed**: Single domain (`IDENTITY_STORE_ID_2`)
**Recommendation**: Start with single domain, architect for multi-domain migration if needed
**Next Step**: Create producer and consumer projects within current domain

The base platform infrastructure (VPC, IAM, S3) supports both approaches - you can add more domains later without changing the foundation.
