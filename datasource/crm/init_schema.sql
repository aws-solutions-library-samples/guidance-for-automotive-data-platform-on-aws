-- Automotive CRM Database Initialization
-- Run this after Aurora cluster is created

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table (CRM users)
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    role VARCHAR(100),
    department VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Accounts
CREATE TABLE accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_name VARCHAR(255) NOT NULL,
    account_type VARCHAR(50),
    phone VARCHAR(50),
    billing_street VARCHAR(255),
    billing_city VARCHAR(100),
    billing_state VARCHAR(50),
    billing_postal_code VARCHAR(20),
    account_owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Contacts
CREATE TABLE contacts (
    contact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(account_id),
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(50),
    mobile_phone VARCHAR(50),
    date_of_birth DATE,
    lead_source VARCHAR(100),
    lifecycle_stage VARCHAR(50),
    customer_since DATE,
    contact_owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Leads
CREATE TABLE leads (
    lead_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name VARCHAR(100),
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    lead_source VARCHAR(100),
    lead_status VARCHAR(50),
    lead_score INT,
    converted_date TIMESTAMP,
    converted_contact_id UUID REFERENCES contacts(contact_id),
    owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Opportunities
CREATE TABLE opportunities (
    opportunity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(account_id),
    contact_id UUID REFERENCES contacts(contact_id),
    opportunity_name VARCHAR(255) NOT NULL,
    stage VARCHAR(50) NOT NULL,
    amount DECIMAL(15,2),
    probability INT,
    close_date DATE,
    vehicle_of_interest VARCHAR(100),
    financing_type VARCHAR(50),
    is_closed BOOLEAN DEFAULT FALSE,
    is_won BOOLEAN DEFAULT FALSE,
    owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Customer Vehicles
CREATE TABLE customer_vehicles (
    vehicle_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID REFERENCES accounts(account_id),
    contact_id UUID REFERENCES contacts(contact_id),
    vin VARCHAR(17) UNIQUE NOT NULL,
    make VARCHAR(100),
    model VARCHAR(100),
    year INT,
    mileage INT,
    purchase_date DATE,
    purchase_price DECIMAL(15,2),
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cases
CREATE TABLE cases (
    case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number VARCHAR(50) UNIQUE NOT NULL,
    account_id UUID REFERENCES accounts(account_id),
    contact_id UUID REFERENCES contacts(contact_id),
    vehicle_id UUID REFERENCES customer_vehicles(vehicle_id),
    subject VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50),
    priority VARCHAR(20),
    case_type VARCHAR(50),
    owner_id UUID REFERENCES users(user_id),
    opened_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_date TIMESTAMP,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Service Appointments
CREATE TABLE service_appointments (
    appointment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(contact_id),
    vehicle_id UUID REFERENCES customer_vehicles(vehicle_id),
    appointment_date TIMESTAMP NOT NULL,
    appointment_type VARCHAR(100),
    status VARCHAR(50),
    estimated_cost DECIMAL(15,2),
    actual_cost DECIMAL(15,2),
    service_advisor_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Campaigns
CREATE TABLE campaigns (
    campaign_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_name VARCHAR(255) NOT NULL,
    campaign_type VARCHAR(100),
    status VARCHAR(50),
    start_date DATE,
    end_date DATE,
    budget DECIMAL(15,2),
    num_sent INT,
    num_converted INT,
    owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Campaign Members
CREATE TABLE campaign_members (
    campaign_member_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES campaigns(campaign_id),
    contact_id UUID REFERENCES contacts(contact_id),
    status VARCHAR(50),
    has_responded BOOLEAN DEFAULT FALSE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Activities
CREATE TABLE activities (
    activity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_type VARCHAR(50),
    subject VARCHAR(255),
    description TEXT,
    status VARCHAR(50),
    due_date TIMESTAMP,
    completed_date TIMESTAMP,
    related_to_type VARCHAR(50),
    related_to_id UUID,
    owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_contacts_account ON contacts(account_id);
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_opportunities_stage ON opportunities(stage);
CREATE INDEX idx_vehicles_vin ON customer_vehicles(vin);
CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_activities_related ON activities(related_to_type, related_to_id);
