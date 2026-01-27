#!/bin/bash
set -e

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "=== Deploying Automotive Data Platform ==="
echo "Region: $REGION"
echo "Account: $ACCOUNT_ID"
echo ""

# Check for existing domain
EXISTING_DOMAIN=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`DomainId`].OutputValue' --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_DOMAIN" ]; then
    echo "✓ Using existing domain: $EXISTING_DOMAIN"
    DOMAIN_ID=$EXISTING_DOMAIN
    ROOT_DOMAIN_UNIT=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`RootDomainUnitId`].OutputValue' --output text)
    MANAGE_ROLE=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`SageMakerManageAccessRoleArn`].OutputValue' --output text)
    PROVISIONING_ROLE=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`SageMakerProvisioningRoleArn`].OutputValue' --output text)
else
    # Step 1: Create Unified Studio domain
    echo "Step 1: Creating Unified Studio domain..."
    aws cloudformation deploy \
        --region $REGION \
        --stack-name automotive-unified-studio-domain \
        --template-file /Users/givenand/Unified-Studio-for-Amazon-Sagemaker/experimental/SMUS-CICD-pipeline-cli/tests/scripts/sagemaker-domain.yaml \
        --parameter-overrides DomainName=automotive-platform-v2 \
        --capabilities CAPABILITY_NAMED_IAM \
        --no-fail-on-empty-changeset

    DOMAIN_ID=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`DomainId`].OutputValue' --output text)
    ROOT_DOMAIN_UNIT=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`RootDomainUnitId`].OutputValue' --output text)
    MANAGE_ROLE=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`SageMakerManageAccessRoleArn`].OutputValue' --output text)
    PROVISIONING_ROLE=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`SageMakerProvisioningRoleArn`].OutputValue' --output text)
    echo "✓ Domain: $DOMAIN_ID"
fi

# Step 2: Create S3 bucket and get VPC
echo ""
echo "Step 2: Setting up shared resources..."
BUCKET_NAME="datazone-environments-$ACCOUNT_ID"
aws s3 mb s3://$BUCKET_NAME --region $REGION 2>/dev/null || echo "✓ Bucket exists"

VPC_ID=$(aws ec2 describe-vpcs --region $REGION --filters "Name=isDefault,Values=false" --query 'Vpcs[0].VpcId' --output text)
SUBNETS=$(aws ec2 describe-subnets --region $REGION --filters "Name=vpc-id,Values=$VPC_ID" --query 'Subnets[0:2].SubnetId' --output text | tr '\t' ',')

echo "✓ VPC: $VPC_ID"

# Step 3: Enable blueprints with S3
echo ""
echo "Step 3: Enabling blueprints..."

aws datazone put-environment-blueprint-configuration \
    --region $REGION --domain-identifier $DOMAIN_ID --environment-blueprint-identifier cjegf7f6kky6w7 \
    --manage-access-role-arn "$MANAGE_ROLE" --provisioning-role-arn "$PROVISIONING_ROLE" \
    --enabled-regions $REGION \
    --regional-parameters "{\"$REGION\":{\"VpcId\":\"$VPC_ID\",\"Subnets\":\"$SUBNETS\",\"S3Location\":\"$BUCKET_NAME\"}}" > /dev/null

aws datazone put-environment-blueprint-configuration \
    --region $REGION --domain-identifier $DOMAIN_ID --environment-blueprint-identifier b5u742v3kgqup3 \
    --manage-access-role-arn "$MANAGE_ROLE" --provisioning-role-arn "$PROVISIONING_ROLE" \
    --enabled-regions $REGION \
    --regional-parameters "{\"$REGION\":{\"VpcId\":\"$VPC_ID\",\"Subnets\":\"$SUBNETS\",\"S3Location\":\"$BUCKET_NAME\"}}" > /dev/null

echo "✓ Tooling and MLExperiments blueprints enabled"

# Step 4: Verify policy grants exist
echo ""
echo "Step 4: Verifying policy grants..."

TOOLING_GRANTS=$(aws datazone list-policy-grants --region $REGION --domain-identifier $DOMAIN_ID --entity-type ENVIRONMENT_BLUEPRINT_CONFIGURATION --policy-type CREATE_ENVIRONMENT_FROM_BLUEPRINT --entity-identifier "$ACCOUNT_ID:cjegf7f6kky6w7" --query 'grantList[0].grantId' --output text 2>/dev/null || echo "")
ML_GRANTS=$(aws datazone list-policy-grants --region $REGION --domain-identifier $DOMAIN_ID --entity-type ENVIRONMENT_BLUEPRINT_CONFIGURATION --policy-type CREATE_ENVIRONMENT_FROM_BLUEPRINT --entity-identifier "$ACCOUNT_ID:b5u742v3kgqup3" --query 'grantList[0].grantId' --output text 2>/dev/null || echo "")

if [ -n "$TOOLING_GRANTS" ] && [ -n "$ML_GRANTS" ]; then
    echo "✓ Policy grants already configured"
else
    echo "⚠️  Policy grants missing - please create manually via console"
    echo "  Domain: $DOMAIN_ID"
    echo "  Blueprints: cjegf7f6kky6w7 (Tooling), b5u742v3kgqup3 (MLExperiments)"
fi

# Step 5: Create or update project profile
echo ""
echo "Step 5: Configuring project profile..."

PROFILE_ID=$(aws datazone list-project-profiles --region $REGION --domain-identifier $DOMAIN_ID --query 'items[0].id' --output text 2>/dev/null || echo "")

if [ -z "$PROFILE_ID" ] || [ "$PROFILE_ID" = "None" ]; then
    PROFILE_OUTPUT=$(aws datazone create-project-profile \
        --region $REGION --domain-identifier $DOMAIN_ID --domain-unit-identifier $ROOT_DOMAIN_UNIT \
        --name "All capabilities" --description "ML and data analytics" \
        --environment-configurations "[{\"name\":\"Tooling\",\"environmentBlueprintId\":\"cjegf7f6kky6w7\",\"awsAccount\":{\"awsAccountId\":\"$ACCOUNT_ID\"},\"awsRegion\":{\"regionName\":\"$REGION\"},\"deploymentOrder\":0},{\"name\":\"MLExperiments\",\"environmentBlueprintId\":\"b5u742v3kgqup3\",\"awsAccount\":{\"awsAccountId\":\"$ACCOUNT_ID\"},\"awsRegion\":{\"regionName\":\"$REGION\"},\"deploymentOrder\":1}]" \
        --output json)
    PROFILE_ID=$(echo "$PROFILE_OUTPUT" | jq -r '.id')
    echo "✓ Created profile: $PROFILE_ID"
else
    aws datazone update-project-profile --region $REGION --domain-identifier $DOMAIN_ID --identifier $PROFILE_ID \
        --environment-configurations "[{\"name\":\"Tooling\",\"environmentBlueprintId\":\"cjegf7f6kky6w7\",\"awsAccount\":{\"awsAccountId\":\"$ACCOUNT_ID\"},\"awsRegion\":{\"regionName\":\"$REGION\"},\"deploymentOrder\":0},{\"name\":\"MLExperiments\",\"environmentBlueprintId\":\"b5u742v3kgqup3\",\"awsAccount\":{\"awsAccountId\":\"$ACCOUNT_ID\"},\"awsRegion\":{\"regionName\":\"$REGION\"},\"deploymentOrder\":1}]" > /dev/null
    echo "✓ Updated profile: $PROFILE_ID"
fi

aws datazone update-project-profile --region $REGION --domain-identifier $DOMAIN_ID --identifier $PROFILE_ID --status ENABLED > /dev/null 2>&1 || true

# Save configuration
mkdir -p /tmp/automotive-platform
cat > /tmp/automotive-platform/config.env << EOF
export DOMAIN_ID=$DOMAIN_ID
export PROFILE_ID=$PROFILE_ID
export ROOT_DOMAIN_UNIT=$ROOT_DOMAIN_UNIT
export REGION=$REGION
export ACCOUNT_ID=$ACCOUNT_ID
EOF

# Step 6: Setup telemetry data source
echo ""
echo "Step 6: Configuring telemetry data source..."

# Check if CM telemetry bucket exists
CM_BUCKET="cms-dev-telemetry-backup-$ACCOUNT_ID"
if aws s3 ls s3://$CM_BUCKET 2>/dev/null; then
    echo "✓ Found CM telemetry bucket: $CM_BUCKET"
    TELEMETRY_BUCKET=$CM_BUCKET
    TELEMETRY_PREFIX="raw-telemetry"
    DATA_SOURCE="cm"
    
    # Check for CM service history
    CM_SERVICE_TABLE=$(aws dynamodb list-tables --region $REGION --query 'TableNames[?contains(@, `service-history`)]|[0]' --output text 2>/dev/null || echo "")
    if [ -n "$CM_SERVICE_TABLE" ] && [ "$CM_SERVICE_TABLE" != "None" ]; then
        echo "✓ Found CM service history: $CM_SERVICE_TABLE"
        SERVICE_HISTORY_TABLE=$CM_SERVICE_TABLE
    fi
else
    echo "⚠️  CM telemetry not found, creating synthetic data..."
    TELEMETRY_BUCKET="tire-telemetry-data-$ACCOUNT_ID"
    TELEMETRY_PREFIX="raw-telemetry"
    DATA_SOURCE="synthetic"
    
    # Create bucket
    aws s3 mb s3://$TELEMETRY_BUCKET --region $REGION 2>/dev/null || echo "Bucket exists"
    
    # Generate synthetic data
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/../scripts/generate-tire-telemetry.py" $TELEMETRY_BUCKET 90 10
    
    # Create synthetic service history
    SERVICE_HISTORY_TABLE="tire-service-history-$ACCOUNT_ID"
    aws dynamodb create-table \
      --region $REGION \
      --table-name $SERVICE_HISTORY_TABLE \
      --attribute-definitions \
        AttributeName=vehicleId,AttributeType=S \
        AttributeName=serviceDate,AttributeType=S \
      --key-schema \
        AttributeName=vehicleId,KeyType=HASH \
        AttributeName=serviceDate,KeyType=RANGE \
      --billing-mode PAY_PER_REQUEST 2>/dev/null || echo "Table exists"
fi

# Save telemetry config
cat >> /tmp/automotive-platform/config.env << EOF
export TELEMETRY_BUCKET=$TELEMETRY_BUCKET
export TELEMETRY_PREFIX=$TELEMETRY_PREFIX
export DATA_SOURCE=$DATA_SOURCE
export SERVICE_HISTORY_TABLE=${SERVICE_HISTORY_TABLE:-}
EOF

echo "✓ Telemetry data source: $DATA_SOURCE ($TELEMETRY_BUCKET)"
if [ -n "$SERVICE_HISTORY_TABLE" ]; then
    echo "✓ Service history: $SERVICE_HISTORY_TABLE"
fi

# Step 7: Publish to DataZone catalog
echo ""
echo "Step 7: Publishing data to DataZone catalog..."

# Create Glue database for telemetry
aws glue create-database \
  --region $REGION \
  --database-input "{
    \"Name\": \"tire_telemetry\",
    \"Description\": \"Tire telemetry data from $DATA_SOURCE source\"
  }" 2>/dev/null || echo "  Telemetry database exists"

# Create Glue crawler for telemetry
aws glue create-crawler \
  --region $REGION \
  --name tire-telemetry-crawler \
  --role "$MANAGE_ROLE" \
  --database-name tire_telemetry \
  --targets "{
    \"S3Targets\": [{
      \"Path\": \"s3://$TELEMETRY_BUCKET/$TELEMETRY_PREFIX/\"
    }]
  }" \
  --schema-change-policy "{
    \"UpdateBehavior\": \"UPDATE_IN_DATABASE\",
    \"DeleteBehavior\": \"LOG\"
  }" 2>/dev/null || echo "  Telemetry crawler exists"

# Run crawler
aws glue start-crawler --region $REGION --name tire-telemetry-crawler 2>/dev/null || true

echo "✓ Telemetry data cataloged in Glue database: tire_telemetry"

# Catalog service history if available
if [ -n "$SERVICE_HISTORY_TABLE" ]; then
    aws glue create-database \
      --region $REGION \
      --database-input "{
        \"Name\": \"vehicle_service_history\",
        \"Description\": \"Vehicle service and maintenance records\"
      }" 2>/dev/null || echo "  Service history database exists"
    
    # Create Glue connection for DynamoDB
    aws glue create-connection \
      --region $REGION \
      --connection-input "{
        \"Name\": \"service-history-dynamodb\",
        \"ConnectionType\": \"CUSTOM\",
        \"ConnectionProperties\": {
          \"CONNECTOR_TYPE\": \"dynamodb\",
          \"CONNECTOR_CLASS_NAME\": \"com.amazonaws.glue.catalog.metastore.DynamoDBStorageHandler\"
        }
      }" 2>/dev/null || echo "  DynamoDB connection exists"
    
    echo "✓ Service history cataloged in Glue database: vehicle_service_history"
fi

# Step 8: Generate and catalog weather data
echo ""
echo "Step 8: Generating weather data..."

WEATHER_BUCKET="weather-data-$ACCOUNT_ID"
aws s3 mb s3://$WEATHER_BUCKET --region $REGION 2>/dev/null || echo "Weather bucket exists"

# Generate synthetic weather data
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/../scripts/generate-weather-data.py" $WEATHER_BUCKET 90 5

# Create Glue database for weather
aws glue create-database \
  --region $REGION \
  --database-input "{
    \"Name\": \"weather_data\",
    \"Description\": \"Weather conditions affecting tire wear\"
  }" 2>/dev/null || echo "  Weather database exists"

# Create Glue crawler for weather
aws glue create-crawler \
  --region $REGION \
  --name weather-data-crawler \
  --role "$MANAGE_ROLE" \
  --database-name weather_data \
  --targets "{
    \"S3Targets\": [{
      \"Path\": \"s3://$WEATHER_BUCKET/weather-data/\"
    }]
  }" \
  --schema-change-policy "{
    \"UpdateBehavior\": \"UPDATE_IN_DATABASE\",
    \"DeleteBehavior\": \"LOG\"
  }" 2>/dev/null || echo "  Weather crawler exists"

# Run crawler
aws glue start-crawler --region $REGION --name weather-data-crawler 2>/dev/null || true

echo "✓ Weather data cataloged in Glue database: weather_data"

# Save weather config
cat >> /tmp/automotive-platform/config.env << EOF
export WEATHER_BUCKET=$WEATHER_BUCKET
EOF

# Step 9: Setup Lake Formation permissions
echo ""
echo "Step 9: Configuring Lake Formation permissions..."

# Grant permissions for Glue crawlers
aws lakeformation grant-permissions \
  --region $REGION \
  --principal DataLakePrincipalIdentifier="$MANAGE_ROLE" \
  --resource '{"Database":{"Name":"tire_telemetry"}}' \
  --permissions "DESCRIBE" "ALTER" "CREATE_TABLE" "DROP" 2>/dev/null || echo "  Telemetry DB permissions exist"

aws lakeformation grant-permissions \
  --region $REGION \
  --principal DataLakePrincipalIdentifier="$MANAGE_ROLE" \
  --resource '{"Database":{"Name":"weather_data"}}' \
  --permissions "DESCRIBE" "ALTER" "CREATE_TABLE" "DROP" 2>/dev/null || echo "  Weather DB permissions exist"

echo "✓ Lake Formation permissions configured"

# Step 10: Publish Glue catalogs to DataZone
echo ""
echo "Step 10: Publishing data sources to DataZone..."

# Create a catalog project for data sources
CATALOG_PROJECT=$(aws datazone create-project \
  --region $REGION \
  --domain-identifier $DOMAIN_ID \
  --name "Data Catalog" \
  --description "Centralized data catalog for all data sources" \
  --project-profile-id $PROFILE_ID \
  --query 'id' \
  --output text 2>&1 || aws datazone list-projects --region $REGION --domain-identifier $DOMAIN_ID --query 'items[?name==`Data Catalog`].id|[0]' --output text)

echo "✓ Catalog project: $CATALOG_PROJECT"

# Add SSO user to catalog project
USER_ID=$(aws identitystore list-users --identity-store-id d-906751a6b3 --query 'Users[0].UserId' --output text 2>/dev/null || echo "")
if [ -n "$USER_ID" ] && [ "$USER_ID" != "None" ]; then
    aws datazone create-project-membership \
      --region $REGION \
      --domain-identifier $DOMAIN_ID \
      --project-identifier $CATALOG_PROJECT \
      --member "{\"userIdentifier\":\"$USER_ID\"}" \
      --designation PROJECT_OWNER 2>/dev/null || echo "  User already member"
    echo "  ✓ User added to catalog project"
fi

# Wait for catalog project environments to be created
echo "  Waiting for catalog project environments..."
sleep 30

# Check if environments are ready
CATALOG_ENV=$(aws datazone list-environments \
  --region $REGION \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $CATALOG_PROJECT \
  --query 'items[?name==`Tooling` && status==`ACTIVE`].id|[0]' \
  --output text 2>/dev/null || echo "")

if [ -z "$CATALOG_ENV" ] || [ "$CATALOG_ENV" = "None" ]; then
    echo "  ⚠️  Catalog project environments not ready yet"
    echo "  Run this after environments are ACTIVE:"
    echo "    make publish-data"
else
    echo "  ✓ Catalog environment ready: $CATALOG_ENV"
    
    # Get IAM connection ID
    CONNECTION_ID=$(aws datazone list-connections \
      --region $REGION \
      --domain-identifier $DOMAIN_ID \
      --project-identifier $CATALOG_PROJECT \
      --query 'items[?name==`project.iam`].connectionId|[0]' \
      --output text)
    
    if [ -z "$CONNECTION_ID" ] || [ "$CONNECTION_ID" = "None" ]; then
        echo "  ⚠️  IAM connection not found, waiting for environment setup..."
    else
        echo "  ✓ IAM connection: $CONNECTION_ID"
        
        # Grant Lake Formation table permissions to catalog project role
        CATALOG_ROLE=$(aws datazone list-environment-actions \
          --region $REGION \
          --domain-identifier $DOMAIN_ID \
          --environment-identifier $CATALOG_ENV \
          --query 'items[0].parameters' --output text 2>/dev/null | grep -o 'datazone_usr_role[^"]*' || echo "")
        
        if [ -n "$CATALOG_ROLE" ]; then
            aws lakeformation grant-permissions \
              --region $REGION \
              --principal DataLakePrincipalIdentifier="arn:aws:iam::$ACCOUNT_ID:role/$CATALOG_ROLE" \
              --resource '{"Table":{"DatabaseName":"tire_telemetry","TableWildcard":{}}}' \
              --permissions "SELECT" "DESCRIBE" 2>/dev/null || true
            
            aws lakeformation grant-permissions \
              --region $REGION \
              --principal DataLakePrincipalIdentifier="arn:aws:iam::$ACCOUNT_ID:role/$CATALOG_ROLE" \
              --resource '{"Table":{"DatabaseName":"weather_data","TableWildcard":{}}}' \
              --permissions "SELECT" "DESCRIBE" 2>/dev/null || true
            
            echo "  ✓ Table permissions granted to catalog role"
        fi
        
        # Create DataZone data sources using IAM connection
        echo "  Creating data sources..."
        
        aws datazone create-data-source \
          --region $REGION \
          --domain-identifier $DOMAIN_ID \
          --project-identifier $CATALOG_PROJECT \
          --connection-identifier $CONNECTION_ID \
          --name "Tire Telemetry" \
          --type GLUE \
          --enable-setting ENABLED \
          --publish-on-import \
          --configuration '{"glueRunConfiguration":{"relationalFilterConfigurations":[{"databaseName":"tire_telemetry"}]}}' \
          2>&1 | grep -q "id" && echo "    ✓ Telemetry" || echo "    Telemetry exists"
        
        aws datazone create-data-source \
          --region $REGION \
          --domain-identifier $DOMAIN_ID \
          --project-identifier $CATALOG_PROJECT \
          --connection-identifier $CONNECTION_ID \
          --name "Weather Data" \
          --type GLUE \
          --enable-setting ENABLED \
          --publish-on-import \
          --configuration '{"glueRunConfiguration":{"relationalFilterConfigurations":[{"databaseName":"weather_data"}]}}' \
          2>&1 | grep -q "id" && echo "    ✓ Weather" || echo "    Weather exists"
        
        if [ -n "$SERVICE_HISTORY_TABLE" ]; then
            aws datazone create-data-source \
              --region $REGION \
              --domain-identifier $DOMAIN_ID \
              --project-identifier $CATALOG_PROJECT \
              --connection-identifier $CONNECTION_ID \
              --name "Service History" \
              --type GLUE \
              --enable-setting ENABLED \
              --publish-on-import \
              --configuration '{"glueRunConfiguration":{"relationalFilterConfigurations":[{"databaseName":"vehicle_service_history"}]}}' \
              2>&1 | grep -q "id" && echo "    ✓ Service History" || echo "    Service History exists"
        fi
        
        # Run data source jobs
        echo "  Publishing to catalog..."
        for DS_ID in $(aws datazone list-data-sources --region $REGION --domain-identifier $DOMAIN_ID --project-identifier $CATALOG_PROJECT --query 'items[].id' --output text); do
            aws datazone start-data-source-run \
              --region $REGION \
              --domain-identifier $DOMAIN_ID \
              --data-source-identifier $DS_ID 2>/dev/null || true
        done
        
        echo "✓ Data sources published to DataZone catalog"
    fi
fi

# Save catalog project ID
cat >> /tmp/automotive-platform/config.env << EOF
export CATALOG_PROJECT=$CATALOG_PROJECT
EOF

echo ""
echo "=== ✓ Platform Deployment Complete ==="
echo ""
echo "Configuration saved to: /tmp/automotive-platform/config.env"
echo ""
echo "Domain: $DOMAIN_ID"
echo "Catalog Project: $CATALOG_PROJECT"
echo ""
if [ -z "$CATALOG_ENV" ] || [ "$CATALOG_ENV" = "None" ]; then
    echo "⚠️  IMPORTANT: Data sources not yet published"
    echo ""
    echo "The Data Catalog project environments are being created (~10 minutes)"
    echo "After environments are ACTIVE, run:"
    echo "  make publish-data"
    echo ""
    echo "Or check status:"
    echo "  aws datazone list-environments --region $REGION \\"
    echo "    --domain-identifier $DOMAIN_ID \\"
    echo "    --project-identifier $CATALOG_PROJECT"
    echo ""
else
    echo "✓ Data sources published to DataZone catalog"
    echo ""
fi
echo "Next: Deploy tire-prediction project"
echo "  cd ~/automotive-tire-prediction-model-on-aws"
echo "  make deploy"
