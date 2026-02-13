import psycopg2
import boto3
import json
import os

# Resolve credentials from Secrets Manager or environment variables
secret_name = os.environ.get('DB_SECRET_NAME', 'cx-crm-db-credentials')

try:
    client = boto3.client('secretsmanager')
    secret = json.loads(client.get_secret_value(SecretId=secret_name)['SecretString'])
    host = secret['host']
    database = secret.get('dbname', 'cx_crm')
    user = secret['username']
    password = secret['password']
except Exception:
    host = os.environ['DB_HOST']
    database = os.environ.get('DB_NAME', 'cx_crm')
    user = os.environ['DB_USER']
    password = os.environ['DB_PASSWORD']

print("Connecting to database...")
conn = psycopg2.connect(
    host=host,
    database=database,
    user=user,
    password=password
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
