# Automotive CRM Database Schema (Aurora PostgreSQL)

## Overview
This schema models a typical automotive CRM system with customer lifecycle management, sales pipeline, service interactions, and marketing automation.

## Core Entities

### 1. Accounts (Companies/Households)
```sql
CREATE TABLE accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_name VARCHAR(255) NOT NULL,
    account_type VARCHAR(50), -- 'Individual', 'Family', 'Business'
    industry VARCHAR(100),
    annual_revenue DECIMAL(15,2),
    number_of_employees INT,
    billing_street VARCHAR(255),
    billing_city VARCHAR(100),
    billing_state VARCHAR(50),
    billing_postal_code VARCHAR(20),
    billing_country VARCHAR(100),
    phone VARCHAR(50),
    website VARCHAR(255),
    account_owner_id UUID,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
```

### 2. Contacts (Individual Customers)
```sql
CREATE TABLE contacts (
    contact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(account_id),
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(50),
    mobile_phone VARCHAR(50),
    date_of_birth DATE,
    gender VARCHAR(20),
    mailing_street VARCHAR(255),
    mailing_city VARCHAR(100),
    mailing_state VARCHAR(50),
    mailing_postal_code VARCHAR(20),
    mailing_country VARCHAR(100),
    contact_owner_id UUID,
    lead_source VARCHAR(100), -- 'Web', 'Referral', 'Dealership', 'Event'
    lifecycle_stage VARCHAR(50), -- 'Lead', 'Prospect', 'Customer', 'Advocate'
    customer_since DATE,
    preferred_contact_method VARCHAR(50),
    do_not_call BOOLEAN DEFAULT FALSE,
    email_opt_out BOOLEAN DEFAULT FALSE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3. Leads (Potential Customers)
```sql
CREATE TABLE leads (
    lead_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name VARCHAR(100),
    last_name VARCHAR(100) NOT NULL,
    company VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    mobile_phone VARCHAR(50),
    lead_source VARCHAR(100),
    lead_status VARCHAR(50), -- 'New', 'Contacted', 'Qualified', 'Unqualified', 'Converted'
    lead_score INT, -- 0-100
    rating VARCHAR(20), -- 'Hot', 'Warm', 'Cold'
    industry VARCHAR(100),
    annual_revenue DECIMAL(15,2),
    number_of_employees INT,
    street VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(50),
    postal_code VARCHAR(20),
    country VARCHAR(100),
    description TEXT,
    converted_date TIMESTAMP,
    converted_account_id UUID REFERENCES accounts(account_id),
    converted_contact_id UUID REFERENCES contacts(contact_id),
    owner_id UUID,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4. Opportunities (Sales Pipeline)
```sql
CREATE TABLE opportunities (
    opportunity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(account_id),
    contact_id UUID REFERENCES contacts(contact_id),
    opportunity_name VARCHAR(255) NOT NULL,
    stage VARCHAR(50) NOT NULL, -- 'Prospecting', 'Qualification', 'Proposal', 'Negotiation', 'Closed Won', 'Closed Lost'
    amount DECIMAL(15,2),
    probability INT, -- 0-100
    close_date DATE,
    next_step VARCHAR(255),
    lead_source VARCHAR(100),
    vehicle_of_interest VARCHAR(100),
    trade_in_vehicle VARCHAR(100),
    trade_in_value DECIMAL(15,2),
    financing_type VARCHAR(50), -- 'Cash', 'Loan', 'Lease'
    is_closed BOOLEAN DEFAULT FALSE,
    is_won BOOLEAN DEFAULT FALSE,
    owner_id UUID,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5. Vehicles (Owned by Customers)
```sql
CREATE TABLE customer_vehicles (
    vehicle_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(account_id),
    contact_id UUID REFERENCES contacts(contact_id),
    vin VARCHAR(17) UNIQUE NOT NULL,
    make VARCHAR(100),
    model VARCHAR(100),
    year INT,
    trim VARCHAR(100),
    color VARCHAR(50),
    mileage INT,
    purchase_date DATE,
    purchase_price DECIMAL(15,2),
    current_value DECIMAL(15,2),
    warranty_expiration DATE,
    registration_expiration DATE,
    insurance_provider VARCHAR(255),
    insurance_policy_number VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 6. Cases (Service/Support Tickets)
```sql
CREATE TABLE cases (
    case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number VARCHAR(50) UNIQUE NOT NULL,
    account_id UUID REFERENCES accounts(account_id),
    contact_id UUID REFERENCES contacts(contact_id),
    vehicle_id UUID REFERENCES customer_vehicles(vehicle_id),
    subject VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50), -- 'New', 'In Progress', 'Escalated', 'Resolved', 'Closed'
    priority VARCHAR(20), -- 'Low', 'Medium', 'High', 'Critical'
    case_type VARCHAR(50), -- 'Technical', 'Billing', 'Service', 'Complaint'
    case_origin VARCHAR(50), -- 'Phone', 'Email', 'Web', 'Mobile App'
    owner_id UUID,
    opened_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_date TIMESTAMP,
    resolution TEXT,
    customer_satisfaction_score INT, -- 1-5
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7. Service Appointments
```sql
CREATE TABLE service_appointments (
    appointment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(account_id),
    contact_id UUID REFERENCES contacts(contact_id),
    vehicle_id UUID REFERENCES customer_vehicles(vehicle_id),
    appointment_date TIMESTAMP NOT NULL,
    appointment_type VARCHAR(100), -- 'Maintenance', 'Repair', 'Recall', 'Inspection'
    service_advisor_id UUID,
    dealership_id UUID,
    status VARCHAR(50), -- 'Scheduled', 'Confirmed', 'In Progress', 'Completed', 'Cancelled'
    estimated_duration INT, -- minutes
    estimated_cost DECIMAL(15,2),
    actual_cost DECIMAL(15,2),
    services_requested TEXT,
    services_completed TEXT,
    notes TEXT,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 8. Activities (Interactions)
```sql
CREATE TABLE activities (
    activity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_type VARCHAR(50), -- 'Call', 'Email', 'Meeting', 'Task', 'SMS'
    subject VARCHAR(255),
    description TEXT,
    status VARCHAR(50), -- 'Planned', 'Completed', 'Cancelled'
    priority VARCHAR(20),
    due_date TIMESTAMP,
    completed_date TIMESTAMP,
    related_to_type VARCHAR(50), -- 'Account', 'Contact', 'Lead', 'Opportunity', 'Case'
    related_to_id UUID,
    owner_id UUID,
    duration_minutes INT,
    outcome VARCHAR(100),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9. Campaigns (Marketing)
```sql
CREATE TABLE campaigns (
    campaign_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_name VARCHAR(255) NOT NULL,
    campaign_type VARCHAR(100), -- 'Email', 'Event', 'Direct Mail', 'Social Media'
    status VARCHAR(50), -- 'Planned', 'In Progress', 'Completed', 'Aborted'
    start_date DATE,
    end_date DATE,
    budget DECIMAL(15,2),
    actual_cost DECIMAL(15,2),
    expected_revenue DECIMAL(15,2),
    expected_response_rate DECIMAL(5,2),
    num_sent INT,
    num_delivered INT,
    num_opened INT,
    num_clicked INT,
    num_converted INT,
    description TEXT,
    owner_id UUID,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 10. Campaign Members
```sql
CREATE TABLE campaign_members (
    campaign_member_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES campaigns(campaign_id),
    contact_id UUID REFERENCES contacts(contact_id),
    lead_id UUID REFERENCES leads(lead_id),
    status VARCHAR(50), -- 'Sent', 'Responded', 'Converted'
    member_status VARCHAR(50),
    first_responded_date TIMESTAMP,
    has_responded BOOLEAN DEFAULT FALSE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 11. Products/Vehicles Catalog
```sql
CREATE TABLE products (
    product_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code VARCHAR(100) UNIQUE,
    product_name VARCHAR(255) NOT NULL,
    product_family VARCHAR(100), -- 'Vehicle', 'Part', 'Service', 'Accessory'
    make VARCHAR(100),
    model VARCHAR(100),
    year INT,
    trim VARCHAR(100),
    msrp DECIMAL(15,2),
    dealer_cost DECIMAL(15,2),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 12. Notes/Attachments
```sql
CREATE TABLE notes (
    note_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_type VARCHAR(50), -- 'Account', 'Contact', 'Opportunity', 'Case'
    parent_id UUID NOT NULL,
    title VARCHAR(255),
    body TEXT,
    is_private BOOLEAN DEFAULT FALSE,
    created_by_id UUID,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 13. Users (CRM Users/Sales Reps)
```sql
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    role VARCHAR(100), -- 'Sales Rep', 'Service Advisor', 'Manager', 'Admin'
    department VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Indexes for Performance

```sql
-- Accounts
CREATE INDEX idx_accounts_owner ON accounts(account_owner_id);
CREATE INDEX idx_accounts_type ON accounts(account_type);

-- Contacts
CREATE INDEX idx_contacts_account ON contacts(account_id);
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contacts_lifecycle ON contacts(lifecycle_stage);

-- Opportunities
CREATE INDEX idx_opportunities_account ON opportunities(account_id);
CREATE INDEX idx_opportunities_stage ON opportunities(stage);
CREATE INDEX idx_opportunities_close_date ON opportunities(close_date);

-- Vehicles
CREATE INDEX idx_vehicles_vin ON customer_vehicles(vin);
CREATE INDEX idx_vehicles_contact ON customer_vehicles(contact_id);

-- Cases
CREATE INDEX idx_cases_contact ON cases(contact_id);
CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_opened ON cases(opened_date);

-- Activities
CREATE INDEX idx_activities_related ON activities(related_to_type, related_to_id);
CREATE INDEX idx_activities_due ON activities(due_date);
```

## Key Relationships

```
Accounts (1) ←→ (N) Contacts
Accounts (1) ←→ (N) Opportunities
Accounts (1) ←→ (N) Vehicles
Contacts (1) ←→ (N) Opportunities
Contacts (1) ←→ (N) Cases
Vehicles (1) ←→ (N) Service Appointments
Campaigns (1) ←→ (N) Campaign Members
```

## Typical CRM Queries

See `sample_queries.sql` for common patterns like:
- Sales pipeline by stage
- Customer lifetime value
- Service history by vehicle
- Campaign effectiveness
- Lead conversion rates
