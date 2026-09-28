import psycopg2
from faker import Faker
import random
from datetime import datetime, timedelta
import os
import json

fake = Faker()

# Configuration
START_DATE = datetime(2015, 1, 1)
END_DATE = datetime(2024, 12, 31)
TOTAL_CUSTOMERS = 500000
TOTAL_DEALERS = 200

# Growth pattern by year
YEARLY_TARGETS = {
    2015: 20000, 2016: 35000, 2017: 55000, 2018: 80000, 2019: 110000,
    2020: 150000, 2021: 200000, 2022: 270000, 2023: 360000, 2024: 500000
}

def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get('DB_HOST'),
        database=os.environ.get('DB_NAME', 'cx_crm'),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD')
    )

def generate_dealers(conn):
    """Generate 200 dealers with varied performance"""
    cursor = conn.cursor()
    regions = ['Northeast', 'Southeast', 'Midwest', 'West']
    tiers = ['Excellent'] * 40 + ['Good'] * 70 + ['Average'] * 60 + ['Poor'] * 30
    random.shuffle(tiers)
    
    dealers = []
    for i in range(TOTAL_DEALERS):
        cursor.execute("""
            INSERT INTO dealers (dealer_name, dealer_code, city, state, region, performance_tier)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING dealer_id
        """, (
            f"{fake.company()} Auto",
            f"DLR{i+1:04d}",
            fake.city(),
            fake.state_abbr(),
            random.choice(regions),
            tiers[i]
        ))
        dealers.append(cursor.fetchone()[0])
    
    conn.commit()
    print(f"✓ Generated {TOTAL_DEALERS} dealers")
    return dealers

def generate_users(conn, dealer_ids):
    """Generate CRM users (sales reps, service advisors)"""
    cursor = conn.cursor()
    roles = ['Sales Rep', 'Service Advisor', 'Manager']
    users = []
    
    # 3 users per dealer
    for dealer_id in dealer_ids:
        for role in roles:
            cursor.execute("""
                INSERT INTO users (username, email, first_name, last_name, role, dealer_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING user_id
            """, (
                fake.user_name(),
                fake.email(),
                fake.first_name(),
                fake.last_name(),
                role,
                dealer_id
            ))
            users.append(cursor.fetchone()[0])
    
    conn.commit()
    print(f"✓ Generated {len(users)} users")
    return users

def generate_customers_by_year(conn, year, target_count, existing_count, user_ids):
    """Generate customers for a specific year"""
    cursor = conn.cursor()
    new_customers = target_count - existing_count
    customers = []
    
    for i in range(new_customers):
        customer_since = fake.date_between(
            start_date=datetime(year, 1, 1),
            end_date=datetime(year, 12, 31)
        )
        
        # Create account
        cursor.execute("""
            INSERT INTO accounts (account_name, account_type, phone, billing_city, 
                                billing_state, billing_postal_code, account_owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING account_id
        """, (
            fake.name(),
            random.choice(['Individual', 'Family']),
            fake.phone_number(),
            fake.city(),
            fake.state_abbr(),
            fake.postcode(),
            random.choice(user_ids)
        ))
        account_id = cursor.fetchone()[0]
        
        # Create contact
        lifecycle = random.choices(
            ['Active', 'At-Risk', 'Churned'],
            weights=[0.60, 0.25, 0.15]
        )[0]
        
        cursor.execute("""
            INSERT INTO contacts (account_id, first_name, last_name, email, phone, 
                                mobile_phone, date_of_birth, customer_since, lifecycle_stage,
                                current_health_score, contact_owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING contact_id
        """, (
            account_id,
            fake.first_name(),
            fake.last_name(),
            fake.email(),
            fake.phone_number(),
            fake.phone_number(),
            fake.date_of_birth(minimum_age=18, maximum_age=80),
            customer_since,
            lifecycle,
            random.randint(20, 95) if lifecycle == 'Active' else random.randint(10, 60),
            random.choice(user_ids)
        ))
        customers.append(cursor.fetchone()[0])
        
        if (i + 1) % 1000 == 0:
            conn.commit()
            print(f"  {year}: {i+1}/{new_customers} customers")
    
    conn.commit()
    print(f"✓ Generated {new_customers} customers for {year}")
    return customers

def generate_vehicles(conn, contact_ids, dealer_ids, year):
    """Generate vehicles for customers (1.5 per customer avg)"""
    cursor = conn.cursor()
    makes = ['Toyota', 'Honda', 'Ford', 'Chevrolet', 'Tesla', 'BMW', 'Mercedes', 'Nissan']
    models = ['Sedan', 'SUV', 'Truck', 'Coupe', 'Hatchback']
    
    vehicle_count = int(len(contact_ids) * 1.5)
    
    for i in range(vehicle_count):
        contact_id = random.choice(contact_ids)
        purchase_date = fake.date_between(
            start_date=datetime(year, 1, 1),
            end_date=datetime(year, 12, 31)
        )
        
        cursor.execute("""
            INSERT INTO customer_vehicles (contact_id, vin, make, model, year, 
                                         purchase_date, purchase_price, purchase_dealer_id,
                                         current_mileage, financing_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            contact_id,
            fake.vin(),
            random.choice(makes),
            random.choice(models),
            random.randint(year-2, year),
            purchase_date,
            random.randint(25000, 75000),
            random.choice(dealer_ids),
            random.randint(5000, 80000),
            random.choice(['Cash', 'Loan', 'Lease'])
        ))
        
        if (i + 1) % 1000 == 0:
            conn.commit()
    
    conn.commit()
    print(f"✓ Generated {vehicle_count} vehicles for {year}")

def generate_interactions(conn, contact_ids, dealer_ids, user_ids, year):
    """Generate interactions (opportunities, cases, appointments, surveys)"""
    cursor = conn.cursor()
    
    # Get vehicles for this batch
    cursor.execute("SELECT vehicle_id, contact_id FROM customer_vehicles WHERE EXTRACT(YEAR FROM purchase_date) = %s", (year,))
    vehicles = cursor.fetchall()
    
    # Opportunities (20% of customers)
    opp_count = int(len(contact_ids) * 0.2)
    for i in range(opp_count):
        cursor.execute("""
            INSERT INTO opportunities (contact_id, dealer_id, opportunity_name, stage,
                                     amount, vehicle_of_interest, close_date, is_won, owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            random.choice(contact_ids),
            random.choice(dealer_ids),
            f"{fake.last_name()} - Vehicle Purchase",
            random.choice(['Prospecting', 'Test Drive', 'Proposal', 'Closed Won', 'Closed Lost']),
            random.randint(25000, 75000),
            random.choice(['Sedan', 'SUV', 'Truck']),
            fake.date_between(start_date=datetime(year, 1, 1), end_date=datetime(year, 12, 31)),
            random.choice([True, False]),
            random.choice(user_ids)
        ))
    
    # Support Cases (30% of customers)
    case_count = int(len(contact_ids) * 0.3)
    for i in range(case_count):
        opened = fake.date_time_between(start_date=datetime(year, 1, 1), end_date=datetime(year, 12, 31))
        status = random.choice(['New', 'In Progress', 'Resolved', 'Closed'])
        
        cursor.execute("""
            INSERT INTO cases (case_number, contact_id, subject, status, priority,
                             case_type, opened_date, closed_date, resolution_time_hours, owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            f"CASE-{year}-{i+1:06d}",
            random.choice(contact_ids),
            fake.sentence(),
            status,
            random.choice(['Low', 'Medium', 'High']),
            random.choice(['Technical', 'Billing', 'Service', 'Complaint']),
            opened,
            opened + timedelta(hours=random.randint(1, 72)) if status in ['Resolved', 'Closed'] else None,
            random.randint(1, 72) if status in ['Resolved', 'Closed'] else None,
            random.choice(user_ids)
        ))
    
    # Service Appointments (50% of vehicles)
    if vehicles:
        appt_count = int(len(vehicles) * 0.5)
        for i in range(appt_count):
            vehicle_id, contact_id = random.choice(vehicles)
            cursor.execute("""
                INSERT INTO service_appointments (contact_id, vehicle_id, dealer_id,
                                                 appointment_date, appointment_type, status,
                                                 actual_cost, wait_time_minutes, service_advisor_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                contact_id,
                vehicle_id,
                random.choice(dealer_ids),
                fake.date_time_between(start_date=datetime(year, 1, 1), end_date=datetime(year, 12, 31)),
                random.choice(['Maintenance', 'Repair', 'Recall']),
                'Completed',
                random.randint(100, 2000),
                random.randint(15, 120),
                random.choice(user_ids)
            ))
    
    # Surveys (25% of customers)
    survey_count = int(len(contact_ids) * 0.25)
    for i in range(survey_count):
        cursor.execute("""
            INSERT INTO surveys (contact_id, survey_type, survey_date, nps_score, csat_score, comments)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            random.choice(contact_ids),
            random.choice(['NPS', 'CSAT', 'Post-Purchase', 'Post-Service']),
            fake.date_between(start_date=datetime(year, 1, 1), end_date=datetime(year, 12, 31)),
            random.randint(0, 10),
            random.randint(1, 5),
            fake.sentence() if random.random() > 0.5 else None
        ))
    
    conn.commit()
    print(f"✓ Generated interactions for {year}")

def main():
    print("Starting CX data generation...")
    print(f"Target: {TOTAL_CUSTOMERS} customers, {TOTAL_DEALERS} dealers, 10 years")
    
    conn = get_db_connection()
    
    # Step 1: Dealers
    dealer_ids = generate_dealers(conn)
    
    # Step 2: Users
    user_ids = generate_users(conn, dealer_ids)
    
    # Step 3: Generate by year with growth pattern
    all_contact_ids = []
    for year in range(2015, 2025):
        target = YEARLY_TARGETS[year]
        existing = len(all_contact_ids)
        
        print(f"\n=== Year {year} (Target: {target} total customers) ===")
        
        # Generate new customers
        new_contacts = generate_customers_by_year(conn, year, target, existing, user_ids)
        all_contact_ids.extend(new_contacts)
        
        # Generate vehicles for new customers
        generate_vehicles(conn, new_contacts, dealer_ids, year)
        
        # Generate interactions for all customers up to this year
        generate_interactions(conn, all_contact_ids, dealer_ids, user_ids, year)
    
    conn.close()
    print("\n✅ Data generation complete!")
    print(f"Total customers: {len(all_contact_ids)}")

if __name__ == "__main__":
    main()
