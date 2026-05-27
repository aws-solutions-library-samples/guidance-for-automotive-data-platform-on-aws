-- CX CRM Database Schema Initialization
-- Run after Aurora cluster is created

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Dealers
CREATE TABLE dealers (
    dealer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dealer_name VARCHAR(255) NOT NULL,
    dealer_code VARCHAR(50) UNIQUE NOT NULL,
    city VARCHAR(100),
    state VARCHAR(50),
    region VARCHAR(50),
    performance_tier VARCHAR(20),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Users (CRM users)
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    role VARCHAR(100),
    dealer_id UUID REFERENCES dealers(dealer_id),
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Accounts
CREATE TABLE accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_name VARCHAR(255) NOT NULL,
    account_type VARCHAR(50),
    phone VARCHAR(50),
    billing_city VARCHAR(100),
    billing_state VARCHAR(50),
    billing_postal_code VARCHAR(20),
    account_owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Contacts (Customer 360 core)
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
    lifecycle_stage VARCHAR(50),
    current_health_score INT,
    last_interaction_date TIMESTAMP,
    lifetime_value DECIMAL(15,2),
    contact_owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Customer Vehicles
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
    financing_type VARCHAR(50),
    warranty_expiration DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Opportunities
CREATE TABLE opportunities (
    opportunity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(contact_id),
    dealer_id UUID REFERENCES dealers(dealer_id),
    opportunity_name VARCHAR(255) NOT NULL,
    stage VARCHAR(50),
    amount DECIMAL(15,2),
    vehicle_of_interest VARCHAR(100),
    close_date DATE,
    is_won BOOLEAN DEFAULT FALSE,
    owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cases (Support Tickets)
CREATE TABLE cases (
    case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number VARCHAR(50) UNIQUE NOT NULL,
    contact_id UUID REFERENCES contacts(contact_id),
    vehicle_id UUID REFERENCES customer_vehicles(vehicle_id),
    subject VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50),
    priority VARCHAR(20),
    case_type VARCHAR(50),
    opened_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_date TIMESTAMP,
    resolution_time_hours INT,
    owner_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Service Appointments
CREATE TABLE service_appointments (
    appointment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(contact_id),
    vehicle_id UUID REFERENCES customer_vehicles(vehicle_id),
    dealer_id UUID REFERENCES dealers(dealer_id),
    appointment_date TIMESTAMP NOT NULL,
    appointment_type VARCHAR(100),
    status VARCHAR(50),
    actual_cost DECIMAL(15,2),
    wait_time_minutes INT,
    service_advisor_id UUID REFERENCES users(user_id),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Surveys
CREATE TABLE surveys (
    survey_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID REFERENCES contacts(contact_id),
    survey_type VARCHAR(50),
    survey_date DATE,
    nps_score INT,
    csat_score INT,
    comments TEXT,
    related_interaction_type VARCHAR(50),
    related_interaction_id UUID,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contacts_lifecycle ON contacts(lifecycle_stage);
CREATE INDEX idx_contacts_health ON contacts(current_health_score);
CREATE INDEX idx_vehicles_vin ON customer_vehicles(vin);
CREATE INDEX idx_vehicles_contact ON customer_vehicles(contact_id);
CREATE INDEX idx_opportunities_stage ON opportunities(stage);
CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_contact ON cases(contact_id);
CREATE INDEX idx_appointments_date ON service_appointments(appointment_date);
CREATE INDEX idx_surveys_contact ON surveys(contact_id);
CREATE INDEX idx_dealers_tier ON dealers(performance_tier);
