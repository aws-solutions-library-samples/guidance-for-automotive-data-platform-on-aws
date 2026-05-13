STAGE ?= dev
AWS_REGION ?= us-east-1
AWS_PROFILE ?= default

.PHONY: install synth deploy upload-data sync-data seed-all seed-identity seed-network seed-parts seed-lifecycle seed-campaigns seed-services create-tables

install:
	pip install -r requirements.txt

synth:
	cdk synth

deploy: ## Deploy the Bedrock Knowledge Base
	CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text) \
	CDK_DEFAULT_REGION=$(AWS_REGION) DEPLOYMENT_STAGE=$(STAGE) \
	cdk deploy --require-approval never --profile $(AWS_PROFILE)
	@echo "✅ Knowledge Base deployed. Set BEDROCK_KB_ID in CVX .env from stack output."

upload-data: ## Upload data-sources/ content to the KB S3 bucket
	@BUCKET=adp-$(STAGE)-vehicle-knowledge-base; \
	echo "Uploading to s3://$$BUCKET ..."; \
	aws s3 sync data-sources/ s3://$$BUCKET/ --exclude "*.DS_Store" --profile $(AWS_PROFILE); \
	echo "✅ Uploaded. Run 'make sync-data' to trigger ingestion."

sync-data: ## Trigger Bedrock KB ingestion for all data sources
	@KB_ID=$$(aws cloudformation describe-stacks \
		--stack-name adp-$(STAGE)-vehicle-knowledge-base \
		--query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseId`].OutputValue' \
		--output text --profile $(AWS_PROFILE)); \
	echo "Syncing KB: $$KB_ID"; \
	for DS_ID in $$(aws bedrock-agent list-data-sources --knowledge-base-id $$KB_ID \
		--query 'dataSourceSummaries[*].dataSourceId' --output text --profile $(AWS_PROFILE)); do \
		echo "  Ingesting: $$DS_ID"; \
		aws bedrock-agent start-ingestion-job --knowledge-base-id $$KB_ID --data-source-id $$DS_ID --profile $(AWS_PROFILE) > /dev/null; \
	done; \
	echo "✅ Ingestion started for all data sources."

# ─── DynamoDB Data Products ───────────────────────────────────────────────────

create-tables: ## Create DynamoDB tables for all 6 data products
	@echo "Creating DynamoDB tables (adp-$(STAGE)-*)..."
	@aws dynamodb create-table --table-name adp-$(STAGE)-vehicle-identity \
		--attribute-definitions AttributeName=vin,AttributeType=S \
		--key-schema AttributeName=vin,KeyType=HASH \
		--billing-mode PAY_PER_REQUEST --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo "  vehicle-identity: exists"
	@aws dynamodb create-table --table-name adp-$(STAGE)-service-network \
		--attribute-definitions AttributeName=centerId,AttributeType=S \
		--key-schema AttributeName=centerId,KeyType=HASH \
		--billing-mode PAY_PER_REQUEST --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo "  service-network: exists"
	@aws dynamodb create-table --table-name adp-$(STAGE)-parts-catalog \
		--attribute-definitions AttributeName=partNumber,AttributeType=S \
		--key-schema AttributeName=partNumber,KeyType=HASH \
		--billing-mode PAY_PER_REQUEST --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo "  parts-catalog: exists"
	@aws dynamodb create-table --table-name adp-$(STAGE)-vehicle-lifecycle \
		--attribute-definitions AttributeName=vin,AttributeType=S \
		--key-schema AttributeName=vin,KeyType=HASH \
		--billing-mode PAY_PER_REQUEST --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo "  vehicle-lifecycle: exists"
	@aws dynamodb create-table --table-name adp-$(STAGE)-campaigns-offers \
		--attribute-definitions AttributeName=campaignId,AttributeType=S \
		--key-schema AttributeName=campaignId,KeyType=HASH \
		--billing-mode PAY_PER_REQUEST --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo "  campaigns-offers: exists"
	@aws dynamodb create-table --table-name adp-$(STAGE)-connected-services \
		--attribute-definitions AttributeName=vin,AttributeType=S \
		--key-schema AttributeName=vin,KeyType=HASH \
		--billing-mode PAY_PER_REQUEST --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo "  connected-services: exists"
	@echo "✅ All tables ready."

seed-identity: ## Seed vehicle identity graph
	python3 scripts/generate-vehicle-identity.py --seed-ddb --stage $(STAGE)

seed-network: ## Seed service center network
	python3 scripts/generate-service-network.py --seed-ddb --stage $(STAGE)

seed-parts: ## Seed parts catalog
	python3 scripts/generate-parts-catalog.py --seed-ddb --stage $(STAGE)

seed-lifecycle: ## Seed vehicle lifecycle data
	python3 scripts/generate-lifecycle-campaigns-services.py --seed-ddb --stage $(STAGE)

seed-all: create-tables seed-identity seed-network seed-parts seed-lifecycle ## Create tables + seed all data products
	@echo "✅ All 6 data products seeded."
