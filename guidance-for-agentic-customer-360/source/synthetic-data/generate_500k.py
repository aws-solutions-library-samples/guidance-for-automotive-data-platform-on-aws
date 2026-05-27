import psycopg2
from faker import Faker
import random
from datetime import datetime, timedelta
import os

fake = Faker()
TOTAL_CUSTOMERS = 500000
TOTAL_DEALERS = 200
YEARLY_TARGETS = {2015: 20000, 2016: 35000, 2017: 55000, 2018: 80000, 2019: 110000, 2020: 150000, 2021: 200000, 2022: 270000, 2023: 360000, 2024: 500000}

def get_db_connection():
    return psycopg2.connect(host=os.environ['DB_HOST'], database=os.environ.get('DB_NAME', 'cx_crm'), user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'])

def generate_dealers(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM dealers")
    if cursor.fetchone()[0] > 0:
        print("Dealers already exist, skipping...")
        cursor.execute("SELECT dealer_id FROM dealers")
        return [row[0] for row in cursor.fetchall()]
    
    regions = ['Northeast', 'Southeast', 'Midwest', 'West']
    tiers = ['Excellent'] * 40 + ['Good'] * 70 + ['Average'] * 60 + ['Poor'] * 30
    random.shuffle(tiers)
    dealers = []
    for i in range(TOTAL_DEALERS):
        cursor.execute("INSERT INTO dealers (dealer_name, dealer_code, city, state, region, performance_tier) VALUES (%s, %s, %s, %s, %s, %s) RETURNING dealer_id", (f"{fake.company()} Auto", f"DLR{i+1:04d}", fake.city(), fake.state_abbr(), random.choice(regions), tiers[i]))
        dealers.append(cursor.fetchone()[0])
    conn.commit()
    print(f"✓ Generated {TOTAL_DEALERS} dealers")
    return dealers

def generate_users(conn, dealer_ids):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] > 0:
        print("Users already exist, skipping...")
        cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in cursor.fetchall()]
    
    roles = ['Sales Rep', 'Service Advisor', 'Manager']
    users = []
    for dealer_id in dealer_ids:
        for role in roles:
            cursor.execute("INSERT INTO users (username, email, first_name, last_name, role, dealer_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING user_id", (fake.user_name(), fake.email(), fake.first_name(), fake.last_name(), role, dealer_id))
            users.append(cursor.fetchone()[0])
    conn.commit()
    print(f"✓ Generated {len(users)} users")
    return users

def generate_customers_by_year(conn, year, target_count, existing_count, user_ids):
    cursor = conn.cursor()
    new_customers = target_count - existing_count
    customers = []
    print(f"Generating {new_customers} new customers for {year}...")
    for i in range(new_customers):
        customer_since = fake.date_between(start_date=datetime(year, 1, 1), end_date=datetime(year, 12, 31))
        cursor.execute("INSERT INTO accounts (account_name, account_type, phone, billing_city, billing_state, billing_postal_code, account_owner_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING account_id", (fake.name(), random.choice(['Individual', 'Family']), fake.phone_number(), fake.city(), fake.state_abbr(), fake.postcode(), random.choice(user_ids)))
        account_id = cursor.fetchone()[0]
        lifecycle = random.choices(['Active', 'At-Risk', 'Churned'], weights=[0.60, 0.25, 0.15])[0]
        cursor.execute("INSERT INTO contacts (account_id, first_name, last_name, email, phone, mobile_phone, date_of_birth, customer_since, lifecycle_stage, current_health_score, contact_owner_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING contact_id", (account_id, fake.first_name(), fake.last_name(), fake.email(), fake.phone_number(), fake.phone_number(), fake.date_of_birth(minimum_age=18, maximum_age=80), customer_since, lifecycle, random.randint(20, 95) if lifecycle == 'Active' else random.randint(10, 60), random.choice(user_ids)))
        customers.append(cursor.fetchone()[0])
        if (i + 1) % 5000 == 0:
            conn.commit()
            print(f"  {year}: {i+1}/{new_customers} customers")
    conn.commit()
    print(f"✓ Year {year} complete: {new_customers} customers")
    return customers

def main():
    print(f"Starting full data generation: {TOTAL_CUSTOMERS} customers")
    conn = get_db_connection()
    dealer_ids = generate_dealers(conn)
    user_ids = generate_users(conn, dealer_ids)
    
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM contacts")
    existing = cursor.fetchone()[0]
    print(f"Existing customers: {existing}")
    
    all_contact_ids = []
    for year in range(2015, 2025):
        target = YEARLY_TARGETS[year]
        current_total = existing + len(all_contact_ids)
        print(f"\n=== Year {year} (Target: {target}, Current: {current_total}) ===")
        if current_total >= target:
            print(f"Already at target, skipping...")
            continue
        new_contacts = generate_customers_by_year(conn, year, target, current_total, user_ids)
        all_contact_ids.extend(new_contacts)
    
    conn.close()
    print(f"\n✅ Complete! Total: {existing + len(all_contact_ids)} customers")

if __name__ == "__main__":
    main()
