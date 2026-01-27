# Automotive CRM Database (Aurora PostgreSQL)

## Overview
A realistic CRM database schema modeled after Salesforce/HubSpot for automotive customer lifecycle management.

## Architecture

```
Aurora PostgreSQL Serverless v2
├── Users (Sales reps, service advisors)
├── Accounts (Households/companies)
├── Contacts (Individual customers)
├── Leads (Potential customers)
├── Opportunities (Sales pipeline)
├── Customer Vehicles (Owned vehicles)
├── Cases (Support tickets)
├── Service Appointments
├── Campaigns (Marketing)
└── Activities (Interactions)
```

## Quick Deploy

### 1. Deploy Aurora Cluster
```bash
cd /Users/givenand/automotive-data-platform-on-aws
cdk deploy AutomotiveCRMStack
```

### 2. Initialize Schema
```bash
# Get database credentials
aws secretsmanager get-secret-value \
  --secret-id automotive-crm-db-credentials \
  --query SecretString --output text | jq -r .password

# Connect and run schema
psql -h <cluster-endpoint> -U crm_admin -d automotive_crm -f datasource/crm/init_schema.sql
```

### 3. Generate Synthetic Data
```bash
export DB_HOST=<cluster-endpoint>
export DB_USER=crm_admin
export DB_PASSWORD=<from-secrets-manager>

python datasource/crm/generate_crm_data.py
```

## Database Schema

### Core Entities
- **Accounts**: Customer households/companies
- **Contacts**: Individual people (linked to accounts)
- **Leads**: Potential customers (not yet converted)
- **Opportunities**: Sales pipeline (vehicle purchases)
- **Customer Vehicles**: Vehicles owned by customers

### Service & Support
- **Cases**: Support tickets and issues
- **Service Appointments**: Scheduled maintenance
- **Activities**: Calls, emails, meetings

### Marketing
- **Campaigns**: Marketing campaigns
- **Campaign Members**: Contact participation

## Common Queries

### Sales Pipeline
```sql
SELECT stage, COUNT(*), SUM(amount) as total_value
FROM opportunities
WHERE is_closed = FALSE
GROUP BY stage
ORDER BY total_value DESC;
```

### Customer Lifetime Value
```sql
SELECT c.contact_id, c.first_name, c.last_name,
       COUNT(DISTINCT v.vehicle_id) as vehicles_owned,
       SUM(o.amount) as total_purchases
FROM contacts c
LEFT JOIN customer_vehicles v ON c.contact_id = v.contact_id
LEFT JOIN opportunities o ON c.contact_id = o.contact_id AND o.is_won = TRUE
GROUP BY c.contact_id, c.first_name, c.last_name
ORDER BY total_purchases DESC;
```

### Service History
```sql
SELECT v.vin, v.make, v.model, 
       COUNT(sa.appointment_id) as service_count,
       SUM(sa.actual_cost) as total_service_cost
FROM customer_vehicles v
LEFT JOIN service_appointments sa ON v.vehicle_id = sa.vehicle_id
GROUP BY v.vehicle_id, v.vin, v.make, v.model;
```

## Data Volumes

**Default Generation**:
- 20 CRM users
- 1,000 accounts
- 2,000 contacts
- 500 opportunities
- 1,500 vehicles

**Scalable**: Adjust counts in `generate_crm_data.py`

## Integration with Data Platform

### Connect to S3 Data Lake
```sql
-- Export to S3 for analytics
COPY (SELECT * FROM opportunities WHERE close_date >= CURRENT_DATE - INTERVAL '30 days')
TO 's3://your-bucket/crm-exports/opportunities.parquet'
WITH (FORMAT PARQUET);
```

### Sync with DynamoDB
Use AWS DMS to replicate operational tables to DynamoDB for low-latency access.

### Query from Athena
Use Athena Federated Query to join CRM data with S3 data lake.

## Cost Optimization

**Aurora Serverless v2**:
- Min capacity: 0.5 ACU (~$0.06/hour when idle)
- Max capacity: 4 ACU (~$0.48/hour at peak)
- Auto-scales based on load

**Estimated Monthly Cost**: $50-200 depending on usage

## Next Steps

1. ✅ Deploy Aurora cluster
2. ✅ Initialize schema
3. ✅ Generate synthetic data
4. Add sample queries and dashboards
5. Integrate with existing telemetry data
6. Set up data exports to S3
