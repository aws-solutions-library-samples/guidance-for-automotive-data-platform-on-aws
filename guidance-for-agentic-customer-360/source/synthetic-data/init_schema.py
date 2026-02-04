import psycopg2
import os
import json
import boto3

def get_db_credentials():
    """Get database credentials from Secrets Manager or environment variables."""
    secret_name = os.environ.get('DB_SECRET_NAME')
    
    if secret_name:
        # Get from Secrets Manager
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response['SecretString'])
        return {
            'host': secret.get('host'),
            'database': secret.get('dbname', 'cx_crm'),
            'user': secret.get('username'),
            'password': secret.get('password')  # nosec B105
        }
    else:
        # Get from environment variables
        return {
            'host': os.environ.get('DB_HOST'),
            'database': os.environ.get('DB_NAME', 'cx_crm'),
            'user': os.environ.get('DB_USER'),
            'password': os.environ.get('DB_PASSWORD')  # nosec B105
        }

creds = get_db_credentials()

print("Connecting to database...")
conn = psycopg2.connect(
    host=creds['host'],
    database=creds['database'],
    user=creds['user'],
    password=creds['password']
)

print("Reading schema file...")
with open('init_cx_crm_schema.sql', 'r') as f:
    schema_sql = f.read()

print("Executing schema...")
cursor = conn.cursor()
cursor.execute(schema_sql)
conn.commit()

print("✓ Schema initialized successfully!")
print("\nTables created:")
cursor.execute("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    ORDER BY table_name
""")
for row in cursor.fetchall():
    print(f"  - {row[0]}")

cursor.close()
conn.close()
