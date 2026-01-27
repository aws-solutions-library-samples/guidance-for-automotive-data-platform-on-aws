import psycopg2
import os

# Connection details
host = "cxcrmstack-cxcrmcluster6c40befe-gzycdxj7qfiu.cluster-cnqi2n6fm8jq.us-east-1.rds.amazonaws.com"
database = "cx_crm"
user = "cx_admin"
password = "2on,7FtaYCH.SvW10,_bW5d5AJqIzE"

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
