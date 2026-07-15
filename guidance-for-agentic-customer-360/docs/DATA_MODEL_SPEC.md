# Customer Experience Analytics - Complete Data Model Specification

## Executive Summary

**Goal**: Answer "Where should we invest to maximize customer satisfaction, loyalty, and revenue?"

**Scale**: 500K customers, 10M interactions, 200 dealers, 10 years of history

**Architecture**: Aurora CRM (operational) → S3 Data Lake (analytics) → Amazon Quick Suite (visualization)

---

## 1. Aurora CRM Schema (Operational Database)

### 1.1 Core Tables

#### users (CRM Users)
```sql
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    role VARCHAR(100), -- 'Sales Rep', 'Service Advisor', 'Manager'
    dealer_id UUID,
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### dealers
```sql
CREATE TABLE dealers (
    dealer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dealer_name VARCHAR(255) NOT NULL,
    dealer_code VARCHAR(50) UNIQUE NOT NULL,
    city VARCHAR(100),
    state VARCHAR(50),
    region VARCHAR(50), -- 'Northeast', 'Southeast', 'Midwest', 'West'
    performance_tier VARCHAR(20), -- 'Excellent', 'Good', 'Average', 'Poor'
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### accounts
```sql
CREATE TABLE accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_name VARCHAR(255) NOT NULL,
    account_type VARCHAR(50), -- 'Individual', 'Family'
    phone VARCHAR(50),
    billing_city VARCHAR(100),
    billing_state VARCHAR(50),
    billing_postal_code VARCHAR(20),
    account_owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### contacts (Customer 360 Core)
```sql
CREATE TABLE contacts (
    contact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(account_id),
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(50),
    mobile_phone VARCHAR(50),
    date_of_birth DATE,
    customer_since DATE,
    lifecycle_stage VARCHAR(50), -- 'Prospect', 'Active', 'At-Risk', 'Churned'
    current_health_score INT, -- 0-100
    last_interaction_date TIMESTAMP,
    lifetime_value DECIMAL(15,2),
    contact_owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### customer_vehicles
```sql
CREATE TABLE customer_vehicles (
    vehicle_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(contact_id),
    vin VARCHAR(17) UNIQUE NOT NULL,
    make VARCHAR(100),
    model VARCHAR(100),
    year INT,
    trim VARCHAR(100),
    purchase_date DATE,
    purchase_price DECIMAL(15,2),
    purchase_dealer_id UUID REFERENCES dealers(dealer_id),
    current_mileage INT,
    financing_type VARCHAR(50), -- 'Cash', 'Loan', 'Lease'
    warranty_expiration DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### opportunities (Sales Pipeline)
```sql
CREATE TABLE opportunities (
    opportunity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(contact_id),
    dealer_id UUID REFERENCES dealers(dealer_id),
    opportunity_name VARCHAR(255) NOT NULL,
    stage VARCHAR(50), -- 'Prospecting', 'Test Drive', 'Proposal', 'Negotiation', 'Closed Won', 'Closed Lost'
    amount DECIMAL(15,2),
    vehicle_of_interest VARCHAR(100),
    close_date DATE,
    is_won BOOLEAN DEFAULT FALSE,
    owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### cases (Support Tickets)
```sql
CREATE TABLE cases (
    case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number VARCHAR(50) UNIQUE NOT NULL,
    contact_id UUID REFERENCES contacts(contact_id),
    vehicle_id UUID REFERENCES customer_vehicles(vehicle_id),
    subject VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50), -- 'New', 'In Progress', 'Resolved', 'Closed'
    priority VARCHAR(20), -- 'Low', 'Medium', 'High', 'Critical'
    case_type VARCHAR(50), -- 'Technical', 'Billing', 'Service', 'Complaint'
    opened_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_date TIMESTAMP,
    resolution_time_hours INT,
    owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### service_appointments
```sql
CREATE TABLE service_appointments (
    appointment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(contact_id),
    vehicle_id UUID REFERENCES customer_vehicles(vehicle_id),
    dealer_id UUID REFERENCES dealers(dealer_id),
    appointment_date TIMESTAMP NOT NULL,
    appointment_type VARCHAR(100), -- 'Maintenance', 'Repair', 'Recall'
    status VARCHAR(50), -- 'Scheduled', 'Completed', 'Cancelled'
    actual_cost DECIMAL(15,2),
    wait_time_minutes INT,
    service_advisor_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### surveys
```sql
CREATE TABLE surveys (
    survey_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(contact_id),
    survey_type VARCHAR(50), -- 'NPS', 'CSAT', 'Post-Purchase', 'Post-Service'
    survey_date DATE,
    nps_score INT, -- 0-10
    csat_score INT, -- 1-5
    comments TEXT,
    related_interaction_type VARCHAR(50), -- 'Purchase', 'Service', 'Support'
    related_interaction_id UUID,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2. S3 Data Lake Structure

```
s3://<DATA_LAKE_BUCKET>/
├── raw/
│   ├── crm-export/
│   │   ├── year=YYYY/month=MM/day=DD/
│   │   │   ├── contacts.parquet
│   │   │   ├── vehicles.parquet
│   │   │   ├── opportunities.parquet
│   │   │   ├── cases.parquet
│   │   │   ├── service_appointments.parquet
│   │   │   └── surveys.parquet
│   ├── dealer-sales/
│   │   └── year=YYYY/month=MM/day=DD/sales.parquet
│   ├── web-analytics/
│   │   └── year=YYYY/month=MM/day=DD/events.json
│   ├── app-analytics/
│   │   └── year=YYYY/month=MM/day=DD/events.json
│   └── contact-center/
│       └── year=YYYY/month=MM/day=DD/calls.json
├── processed/
│   ├── customer-360/
│   │   └── year=YYYY/month=MM/day=DD/customer_360.parquet
│   ├── interactions/
│   │   └── year=YYYY/month=MM/day=DD/interactions.parquet
│   └── health-metrics/
│       └── year=YYYY/month=MM/day=DD/health_metrics.parquet
└── analytics/
    ├── daily-summaries/
    ├── customer-segments/
    └── investment-priorities/
```

---

## 3. Unified Data Schemas (S3)

### 3.1 customer_360 (Processed)
```
customer_id: STRING (UUID)
account_id: STRING (UUID)
first_name: STRING
last_name: STRING
email: STRING
phone: STRING
customer_since_date: DATE
lifecycle_stage: STRING
current_health_score: INT
churn_probability: DECIMAL
lifetime_value: DECIMAL
total_vehicles_owned: INT
total_purchases: DECIMAL
total_service_spend: DECIMAL
last_purchase_date: DATE
last_service_date: DATE
last_support_ticket_date: DATE
last_survey_date: DATE
last_app_login_date: DATE
days_since_last_interaction: INT
preferred_dealer_id: STRING
snapshot_date: DATE
```

### 3.2 customer_interactions (Unified Event Log)
```
interaction_id: STRING (UUID)
customer_id: STRING (UUID)
interaction_date: TIMESTAMP
interaction_type: STRING -- 'Purchase', 'Service', 'Support', 'Digital', 'Survey'
interaction_channel: STRING -- 'Dealer', 'Service Center', 'Website', 'App', 'Call Center'
interaction_subtype: STRING -- 'Page View', 'Test Drive', 'Ticket Created', etc.
dealer_id: STRING (nullable)
vehicle_id: STRING (nullable)
revenue_amount: DECIMAL (nullable)
satisfaction_score: INT (nullable)
outcome: STRING -- 'Positive', 'Neutral', 'Negative'
metadata: JSON -- Additional context
```

### 3.3 customer_health_metrics (Daily Calculated)
```
metric_id: STRING (UUID)
customer_id: STRING (UUID)
metric_date: DATE
health_score: INT (0-100)
recency_score: INT
satisfaction_score: INT
support_score: INT
engagement_score: INT
payment_score: INT
churn_probability: DECIMAL (0-1)
churn_risk_level: STRING -- 'Low', 'Medium', 'High'
revenue_at_risk: DECIMAL
contributing_factors: JSON -- What's driving the score
recommended_actions: JSON -- Next best actions
```

### 3.4 dealer_sales (Raw)
```
sale_id: STRING (UUID)
customer_id: STRING (UUID)
vehicle_id: STRING (UUID)
dealer_id: STRING (UUID)
sale_date: DATE
sale_amount: DECIMAL
vehicle_make: STRING
vehicle_model: STRING
vehicle_year: INT
financing_type: STRING
trade_in_value: DECIMAL (nullable)
salesperson_id: STRING (UUID)
```

### 3.5 web_analytics (Raw)
```
event_id: STRING (UUID)
session_id: STRING
customer_id: STRING (nullable - may be anonymous)
event_type: STRING -- 'page_view', 'form_submit', 'vehicle_config', 'test_drive_request'
page_url: STRING
timestamp: TIMESTAMP
device_type: STRING -- 'Desktop', 'Mobile', 'Tablet'
referrer: STRING
duration_seconds: INT
```

### 3.6 app_analytics (Raw)
```
event_id: STRING (UUID)
session_id: STRING
customer_id: STRING
event_type: STRING -- 'app_open', 'feature_use', 'screen_view', 'error'
screen_name: STRING
timestamp: TIMESTAMP
app_version: STRING
device_os: STRING
device_model: STRING
```

### 3.7 contact_center_calls (Raw)
```
call_id: STRING (UUID)
customer_id: STRING
call_date: TIMESTAMP
call_duration_seconds: INT
call_outcome: STRING -- 'Resolved', 'Escalated', 'Callback Required'
issue_category: STRING -- 'Technical', 'Billing', 'Service', 'General'
sentiment_score: DECIMAL (-1 to 1)
agent_id: STRING (UUID)
transcript_summary: TEXT
```

---

## 4. Health Score Calculation Logic

### Daily Batch Job (Glue/Lambda)

```python
def calculate_health_score(customer_id, calculation_date):
    # 1. Recency Score (30%)
    last_purchase = get_last_purchase_date(customer_id)
    last_service = get_last_service_date(customer_id)
    last_interaction = max(last_purchase, last_service)
    days_since = (calculation_date - last_interaction).days
    
    if days_since <= 180: recency_score = 100
    elif days_since <= 365: recency_score = 80
    elif days_since <= 730: recency_score = 60
    elif days_since <= 1095: recency_score = 40
    else: recency_score = 20
    
    # 2. Satisfaction Score (25%)
    latest_nps = get_latest_nps(customer_id)
    if latest_nps >= 9: satisfaction_score = 100
    elif latest_nps >= 7: satisfaction_score = 70
    elif latest_nps >= 0: satisfaction_score = 30
    else: satisfaction_score = 50  # No survey
    
    # 3. Support Score (20%)
    tickets_90d = count_tickets_last_90_days(customer_id)
    if tickets_90d == 0: support_score = 100
    elif tickets_90d <= 2: support_score = 80
    elif tickets_90d <= 5: support_score = 60
    else: support_score = 30
    
    # 4. Engagement Score (15%)
    app_sessions_30d = count_app_sessions_last_30_days(customer_id)
    if app_sessions_30d >= 10: engagement_score = 100
    elif app_sessions_30d >= 5: engagement_score = 80
    elif app_sessions_30d >= 1: engagement_score = 60
    else: engagement_score = 30
    
    # 5. Payment Score (10%)
    payment_status = get_payment_status(customer_id)
    if payment_status == 'current': payment_score = 100
    elif payment_status == 'late_1_30': payment_score = 70
    else: payment_score = 30
    
    # Weighted Total
    health_score = (
        recency_score * 0.30 +
        satisfaction_score * 0.25 +
        support_score * 0.20 +
        engagement_score * 0.15 +
        payment_score * 0.10
    )
    
    # Churn Probability
    if health_score < 40: churn_prob = 0.75
    elif health_score < 60: churn_prob = 0.50
    else: churn_prob = 0.15
    
    return {
        'health_score': int(health_score),
        'churn_probability': churn_prob,
        'recency_score': recency_score,
        'satisfaction_score': satisfaction_score,
        'support_score': support_score,
        'engagement_score': engagement_score,
        'payment_score': payment_score
    }
```

---

## 5. Investment Priority Calculation

```python
def calculate_investment_priorities():
    issues = [
        {
            'issue': 'Service Center Wait Times',
            'affected_customers': count_customers_with_long_wait_times(),
            'avg_revenue_per_customer': 2000,  # Annual service revenue
            'health_score_impact': -20,
            'category': 'Service Operations'
        },
        {
            'issue': 'Mobile App Crashes',
            'affected_customers': count_customers_with_app_errors(),
            'avg_revenue_per_customer': 500,  # Engagement value
            'health_score_impact': -10,
            'category': 'Digital Experience'
        },
        {
            'issue': 'Dealer Sales Process',
            'affected_customers': count_lost_opportunities(),
            'avg_revenue_per_customer': 35000,  # Vehicle purchase
            'health_score_impact': -30,
            'category': 'Sales'
        }
    ]
    
    for issue in issues:
        issue['revenue_at_risk'] = (
            issue['affected_customers'] * 
            issue['avg_revenue_per_customer'] * 
            abs(issue['health_score_impact']) / 100
        )
        issue['priority_score'] = issue['revenue_at_risk']
    
    return sorted(issues, key=lambda x: x['priority_score'], reverse=True)
```

---

## 6. Synthetic Data Generation Specs

### Scale
- **Customers**: 500,000
- **Dealers**: 200 (varied performance)
- **Vehicles**: 750,000 (1.5 per customer avg)
- **Interactions**: 10,000,000 over 10 years
- **Time Period**: 2015-01-01 to 2024-12-31

### Growth Pattern
```
Year 1 (2015): 20,000 customers, 500K interactions
Year 2 (2016): 35,000 customers, 700K interactions
Year 3 (2017): 55,000 customers, 900K interactions
Year 4 (2018): 80,000 customers, 1.1M interactions
Year 5 (2019): 110,000 customers, 1.3M interactions
Year 6 (2020): 150,000 customers, 1.5M interactions
Year 7 (2021): 200,000 customers, 1.7M interactions
Year 8 (2022): 270,000 customers, 1.9M interactions
Year 9 (2023): 360,000 customers, 2.1M interactions
Year 10 (2024): 500,000 customers, 2.3M interactions
```

### Dealer Performance Distribution
- Excellent (20%): 40 dealers - High satisfaction, low wait times
- Good (35%): 70 dealers - Above average
- Average (30%): 60 dealers - Meets standards
- Poor (15%): 30 dealers - Below standards, high complaints

### Customer Lifecycle Distribution
- Active (60%): 300,000 customers
- At-Risk (25%): 125,000 customers
- Churned (15%): 75,000 customers

---

## 7. ETL Pipeline Design

### Daily Pipeline
```
1. Aurora Export (2 AM)
   - Export all tables to S3 raw/crm-export/
   - Glue job: aurora_to_s3_export

2. Data Processing (3 AM)
   - Glue job: process_customer_360
   - Glue job: process_interactions
   - Output to processed/ layer

3. Health Score Calculation (4 AM)
   - Glue job: calculate_health_scores
   - Output to processed/health-metrics/

4. Analytics Aggregation (5 AM)
   - Glue job: generate_daily_summaries
   - Glue job: calculate_investment_priorities
   - Output to analytics/ layer

5. Amazon Quick Suite Refresh (6 AM)
   - Refresh SPICE datasets
```

---

## 8. Amazon Quick Suite Dashboard Specs

### Dashboard 1: Executive Overview
- Overall NPS trend (line chart)
- Customer health distribution (pie chart)
- Revenue at risk by segment (bar chart)
- Top 5 investment priorities (table)

### Dashboard 2: Dealer Performance
- Dealer satisfaction heatmap (by region)
- Sales conversion by dealer (scatter plot)
- Service wait times by dealer (bar chart)
- Dealer performance tier distribution

### Dashboard 3: Customer Journey
- Journey stage funnel
- Drop-off points analysis
- Channel effectiveness
- Time to purchase trends

### Dashboard 4: Investment Priorities
- Issue impact matrix (bubble chart)
- Affected customers by issue
- Revenue at risk by category
- ROI projections

---

## Next Steps

1. ✅ Data model approved
2. Create Aurora CRM stack (CDK)
3. Create synthetic data generators
4. Build ETL pipelines (Glue)
5. Set up Amazon Quick Suite dashboards
6. Deploy and test

**Ready to proceed with implementation?**
