#!/bin/bash

# Export all Athena views and tables from cx_analytics database
# Usage: ./export-athena-views.sh [profile-name] [region]

PROFILE=${1:-default}
REGION=${2:-us-east-1}
DATABASE="cx_analytics"
OUTPUT_DIR="../../source/athena-queries/ddl"

mkdir -p "$OUTPUT_DIR"

echo "Exporting tables and views from $DATABASE..."

# Get all tables
TABLES=$(aws glue get-tables \
  --database-name "$DATABASE" \
  --profile "$PROFILE" \
  --region "$REGION" \
  --query 'TableList[*].Name' \
  --output text)

for TABLE in $TABLES; do
    echo "Exporting $TABLE..."
    
    # Get table details
    TABLE_INFO=$(aws glue get-table \
      --database-name "$DATABASE" \
      --name "$TABLE" \
      --profile "$PROFILE" \
      --region "$REGION")
    
    # Check if it's a view
    IS_VIEW=$(echo "$TABLE_INFO" | jq -r '.Table.TableType')
    
    if [ "$IS_VIEW" == "VIRTUAL_VIEW" ]; then
        # Extract view definition
        VIEW_SQL=$(echo "$TABLE_INFO" | jq -r '.Table.ViewOriginalText')
        
        # Decode base64 if needed (Presto views are base64 encoded)
        if [[ "$VIEW_SQL" == "/* Presto View:"* ]]; then
            ENCODED=$(echo "$VIEW_SQL" | sed 's/.*: \(.*\) \*\//\1/')
            DECODED=$(echo "$ENCODED" | base64 -d 2>/dev/null || echo "$ENCODED")
            VIEW_SQL=$(echo "$DECODED" | jq -r '.originalSql' 2>/dev/null || echo "$VIEW_SQL")
        fi
        
        # Write view DDL
        cat > "$OUTPUT_DIR/${TABLE}.sql" <<EOF
-- View: $TABLE
-- Database: $DATABASE
-- Type: Virtual View

CREATE OR REPLACE VIEW $DATABASE.$TABLE AS
$VIEW_SQL;
EOF
    else
        # Extract table DDL
        LOCATION=$(echo "$TABLE_INFO" | jq -r '.Table.StorageDescriptor.Location')
        COLUMNS=$(echo "$TABLE_INFO" | jq -r '.Table.StorageDescriptor.Columns[] | "    \(.Name) \(.Type),"' | sed '$ s/,$//')
        PARTITIONS=$(echo "$TABLE_INFO" | jq -r '.Table.PartitionKeys[]? | "    \(.Name) \(.Type),"' | sed '$ s/,$//')
        
        # Write table DDL
        cat > "$OUTPUT_DIR/${TABLE}.sql" <<EOF
-- Table: $TABLE
-- Database: $DATABASE
-- Type: External Table
-- Location: $LOCATION

CREATE EXTERNAL TABLE IF NOT EXISTS $DATABASE.$TABLE (
$COLUMNS
)
EOF
        
        if [ -n "$PARTITIONS" ]; then
            cat >> "$OUTPUT_DIR/${TABLE}.sql" <<EOF
PARTITIONED BY (
$PARTITIONS
)
EOF
        fi
        
        cat >> "$OUTPUT_DIR/${TABLE}.sql" <<EOF
STORED AS PARQUET
LOCATION '$LOCATION'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
EOF
    fi
    
    echo "  ✓ Exported to $OUTPUT_DIR/${TABLE}.sql"
done

echo ""
echo "Export complete! Files saved to $OUTPUT_DIR/"
echo "Total tables/views exported: $(echo $TABLES | wc -w)"
