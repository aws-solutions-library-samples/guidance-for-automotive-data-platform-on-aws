import psycopg2
from faker import Faker
import random
from datetime import datetime, timedelta
import os

fake = Faker()

def get_db_connection():
    """Get database connection from environment or AWS Secrets Manager"""
    return psycopg2.connect(
        host=os.environ.get('DB_HOST'),
        database=os.environ.get('DB_NAME', 'automotive_crm'),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD')
    )

def generate_users(conn, count=20):
    """Generate CRM users (sales reps, service advisors)"""
    cursor = conn.cursor()
    roles = ['Sales Rep', 'Service Advisor', 'Manager', 'Admin']
    departments = ['Sales', 'Service', 'Marketing', 'Management']
    
    for _ in range(count):
        cursor.execute("""
            INSERT INTO users (username, email, first_name, last_name, role, department)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING user_id
        """, (
            fake.user_name(),
            fake.email(),
            fake.first_name(),
            fake.last_name(),
            random.choice(roles),
            random.choice(departments)
        ))
    conn.commit()
    print(f"Generated {count} users")

def generate_accounts(conn, count=1000):
    """Generate customer accounts"""
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE role = 'Sales Rep'")
    owners = [row[0] for row in cursor.fetchall()]
    
    for _ in range(count):
        cursor.execute("""
            INSERT INTO accounts (account_name, account_type, phone, billing_city, 
                                billing_state, billing_postal_code, account_owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING account_id
        """, (
            fake.name() if random.random() > 0.3 else fake.company(),
            random.choice(['Individual', 'Family', 'Business']),
            fake.phone_number(),
            fake.city(),
            fake.state_abbr(),
            fake.postcode(),
            random.choice(owners)
        ))
    conn.commit()
    print(f"Generated {count} accounts")

def generate_contacts(conn, count=2000):
    """Generate contacts linked to accounts"""
    cursor = conn.cursor()
    cursor.execute("SELECT account_id FROM accounts")
    accounts = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT user_id FROM users WHERE role = 'Sales Rep'")
    owners = [row[0] for row in cursor.fetchall()]
    
    stages = ['Lead', 'Prospect', 'Customer', 'Advocate']
    sources = ['Web', 'Referral', 'Dealership', 'Event', 'Social Media']
    
    for _ in range(count):
        cursor.execute("""
            INSERT INTO contacts (account_id, first_name, last_name, email, phone, 
                                mobile_phone, date_of_birth, lead_source, lifecycle_stage,
                                customer_since, contact_owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING contact_id
        """, (
            random.choice(accounts),
            fake.first_name(),
            fake.last_name(),
            fake.email(),
            fake.phone_number(),
            fake.phone_number(),
            fake.date_of_birth(minimum_age=18, maximum_age=80),
            random.choice(sources),
            random.choice(stages),
            fake.date_between(start_date='-5y', end_date='today'),
            random.choice(owners)
        ))
    conn.commit()
    print(f"Generated {count} contacts")

def generate_opportunities(conn, count=500):
    """Generate sales opportunities"""
    cursor = conn.cursor()
    cursor.execute("SELECT contact_id, account_id FROM contacts")
    contacts = cursor.fetchall()
    cursor.execute("SELECT user_id FROM users WHERE role = 'Sales Rep'")
    owners = [row[0] for row in cursor.fetchall()]
    
    stages = ['Prospecting', 'Qualification', 'Proposal', 'Negotiation', 'Closed Won', 'Closed Lost']
    vehicles = ['Model S', 'Model 3', 'F-150', 'Silverado', 'Camry', 'Accord', 'RAV4']
    
    for _ in range(count):
        contact_id, account_id = random.choice(contacts)
        stage = random.choice(stages)
        is_closed = stage in ['Closed Won', 'Closed Lost']
        
        cursor.execute("""
            INSERT INTO opportunities (account_id, contact_id, opportunity_name, stage,
                                     amount, probability, close_date, vehicle_of_interest,
                                     financing_type, is_closed, is_won, owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            account_id,
            contact_id,
            f"{fake.last_name()} - {random.choice(vehicles)}",
            stage,
            random.randint(25000, 75000),
            {'Prospecting': 10, 'Qualification': 25, 'Proposal': 50, 
             'Negotiation': 75, 'Closed Won': 100, 'Closed Lost': 0}[stage],
            fake.date_between(start_date='today', end_date='+90d'),
            random.choice(vehicles),
            random.choice(['Cash', 'Loan', 'Lease']),
            is_closed,
            stage == 'Closed Won',
            random.choice(owners)
        ))
    conn.commit()
    print(f"Generated {count} opportunities")

def generate_vehicles(conn, count=1500):
    """Generate customer vehicles"""
    cursor = conn.cursor()
    cursor.execute("SELECT contact_id, account_id FROM contacts WHERE lifecycle_stage = 'Customer'")
    customers = cursor.fetchall()
    
    makes = ['Toyota', 'Honda', 'Ford', 'Chevrolet', 'Tesla', 'BMW']
    models = ['Sedan', 'SUV', 'Truck', 'Coupe']
    
    for _ in range(min(count, len(customers))):
        contact_id, account_id = random.choice(customers)
        cursor.execute("""
            INSERT INTO customer_vehicles (account_id, contact_id, vin, make, model, 
                                         year, mileage, purchase_date, purchase_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            account_id,
            contact_id,
            fake.vin(),
            random.choice(makes),
            random.choice(models),
            random.randint(2018, 2024),
            random.randint(5000, 80000),
            fake.date_between(start_date='-5y', end_date='today'),
            random.randint(25000, 75000)
        ))
    conn.commit()
    print(f"Generated {count} vehicles")

def main():
    conn = get_db_connection()
    
    print("Generating CRM data...")
    generate_users(conn, 20)
    generate_accounts(conn, 1000)
    generate_contacts(conn, 2000)
    generate_opportunities(conn, 500)
    generate_vehicles(conn, 1500)
    
    conn.close()
    print("Done!")

if __name__ == "__main__":
    main()
