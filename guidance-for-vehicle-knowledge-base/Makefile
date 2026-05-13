STAGE ?= dev
AWS_REGION ?= us-east-1
AWS_PROFILE ?= default

.PHONY: install synth deploy upload-data sync-data

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
