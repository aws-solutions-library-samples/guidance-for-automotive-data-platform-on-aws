.PHONY: help install bootstrap phase1 phase2 phase3 phase4 deploy-all verify clean

# Colors
GREEN := \033[0;32m
BLUE := \033[0;34m
YELLOW := \033[0;33m
NC := \033[0m

# Configuration
AWS_REGION ?= $(shell aws configure get region --profile $(AWS_PROFILE) 2>/dev/null || echo "us-east-1")
DEPLOYMENT_STAGE ?= dev
CUSTOMER_COUNT ?= 500000

# AWS Profile Selection
AWS_PROFILES := $(shell grep '^\[' ~/.aws/credentials 2>/dev/null | sed 's/\[//g' | sed 's/\]//g' | sort || echo "default")
PROFILE_COUNT := $(shell echo $(AWS_PROFILES) | wc -w)

# Auto-select profile if only one exists
ifeq ($(PROFILE_COUNT),1)
    AWS_PROFILE := $(AWS_PROFILES)
else
    ifndef AWS_PROFILE
        AWS_PROFILE := default
    endif
endif

STACK_PREFIX := cx360-$(DEPLOYMENT_STAGE)

help: ## Show help
	@echo "$(BLUE)🚀 Agentic Customer 360 Deployment$(NC)"
	@echo "======================================"
	@echo ""
	@echo "$(GREEN)Configuration:$(NC)"
	@echo "  AWS Profile: $(YELLOW)$(AWS_PROFILE)$(NC)"
	@echo "  AWS Region:  $(YELLOW)$(AWS_REGION)$(NC)"
	@echo "  Stage:       $(YELLOW)$(DEPLOYMENT_STAGE)$(NC)"
	@echo ""
	@echo "$(GREEN)Available Profiles:$(NC)"
	@for profile in $(AWS_PROFILES); do \
		if [ "$$profile" = "$(AWS_PROFILE)" ]; then \
			echo "  → $$profile (active)"; \
		else \
			echo "    $$profile"; \
		fi; \
	done
	@echo ""
	@echo "$(GREEN)Quick Start:$(NC)"
	@echo "  make deploy                       - Interactive deployment"
	@echo "  make bootstrap                    - Bootstrap CDK (one-time)"
	@echo "  make deploy-all                   - Deploy everything (non-interactive)"
	@echo ""
	@echo "$(GREEN)Custom Profile/Region:$(NC)"
	@echo "  AWS_PROFILE=myprofile make deploy-all"
	@echo "  AWS_REGION=us-west-2 make deploy-all"
	@echo ""
	@echo "$(GREEN)Manual Deployment Phases:$(NC)"
	@echo "  make phase1       - Data Lake (S3 + Glue + Athena)"
	@echo "  make phase2       - ETL Jobs (Glue)"
	@echo "  make phase3       - Generate Data"
	@echo "  make phase4       - Amazon Quick Suite Dashboards"
	@echo "  make phase5       - Bedrock Agents & Knowledge Base"
	@echo ""
	@echo "$(GREEN)Other Commands:$(NC)"
	@echo "  make install      - Install dependencies"
	@echo "  make verify       - Verify deployment"
	@echo "  make clean        - Delete all"

deploy: ## Interactive deployment with profile and region selection
	@echo "$(BLUE)🚀 Customer 360 Interactive Deployment$(NC)"
	@echo "========================================"
	@echo ""
	@echo "$(GREEN)Available AWS Profiles:$(NC)"
	@all_profiles=$$(grep '^\[' ~/.aws/credentials 2>/dev/null | sed 's/\[//g' | sed 's/\]//g' | sort); \
	if [ -z "$$all_profiles" ]; then \
		all_profiles="default"; \
	fi; \
	echo "$$all_profiles" | nl -v0; \
	echo ""; \
	current_profile="$(AWS_PROFILE)"; \
	current_region="$(AWS_REGION)"; \
	if [ -n "$$current_profile" ] && echo "$$all_profiles" | grep -q "^$$current_profile$$"; then \
		profile_num=$$(echo "$$all_profiles" | grep -n "^$$current_profile$$" | cut -d: -f1); \
		profile_num=$$(($$profile_num - 1)); \
		echo "$(GREEN)✓ Current AWS_PROFILE: $$current_profile (option $$profile_num)$(NC)"; \
		if [ -n "$$current_region" ]; then \
			echo "$(GREEN)✓ Current AWS_REGION: $$current_region$(NC)"; \
		fi; \
		echo ""; \
		read -p "Select profile number (press Enter for current): " profile_choice; \
		if [ -z "$$profile_choice" ]; then \
			selected_profile="$$current_profile"; \
		else \
			profile_index=$$(($$profile_choice + 1)); \
			selected_profile=$$(echo "$$all_profiles" | sed -n "$${profile_index}p"); \
		fi; \
	else \
		read -p "Select profile number: " profile_choice; \
		profile_index=$$(($$profile_choice + 1)); \
		selected_profile=$$(echo "$$all_profiles" | sed -n "$${profile_index}p"); \
	fi; \
	if [ -z "$$selected_profile" ]; then \
		echo "$(RED)❌ Invalid profile selection$(NC)"; \
		exit 1; \
	fi; \
	echo "$(GREEN)✅ Selected profile: $$selected_profile$(NC)"; \
	echo ""; \
	echo "$(GREEN)AWS Region Options:$(NC)"; \
	echo "1. us-east-1 (recommended for QuickSight)"; \
	echo "2. us-west-2"; \
	echo "3. eu-west-1"; \
	echo "4. Custom region"; \
	echo ""; \
	if [ -n "$$current_region" ]; then \
		echo "$(GREEN)✓ Current region: $$current_region$(NC)"; \
		read -p "Select region (1-4, or press Enter for current): " region_choice; \
	else \
		read -p "Select region (1-4): " region_choice; \
	fi; \
	if [ -z "$$region_choice" ] && [ -n "$$current_region" ]; then \
		selected_region="$$current_region"; \
	else \
		case $$region_choice in \
			1) selected_region="us-east-1" ;; \
			2) selected_region="us-west-2" ;; \
			3) selected_region="eu-west-1" ;; \
			4) read -p "Enter custom region: " selected_region ;; \
			*) echo "$(RED)❌ Invalid region selection$(NC)"; exit 1 ;; \
		esac; \
	fi; \
	echo "$(GREEN)✅ Selected region: $$selected_region$(NC)"; \
	echo ""; \
	echo "$(GREEN)Deployment Options:$(NC)"; \
	echo "1. Bootstrap CDK (one-time setup)"; \
	echo "2. Deploy All (phases 1-5)"; \
	echo "3. Phase 1: Data Lake"; \
	echo "4. Phase 2: ETL + Prerequisites"; \
	echo "5. Phase 3: Generate Data"; \
	echo "6. Phase 4: QuickSight Dashboard"; \
	echo "7. Phase 5: Bedrock Agent"; \
	echo ""; \
	read -p "Select deployment option (1-7): " deploy_choice; \
	echo ""; \
	case $$deploy_choice in \
		1) echo "$(BLUE)🚀 Bootstrapping CDK$(NC)"; \
		   $(MAKE) bootstrap AWS_PROFILE=$$selected_profile AWS_REGION=$$selected_region ;; \
		2) echo "$(BLUE)🚀 Deploying All Phases$(NC)"; \
		   $(MAKE) deploy-all AWS_PROFILE=$$selected_profile AWS_REGION=$$selected_region ;; \
		3) echo "$(BLUE)🚀 Phase 1: Data Lake$(NC)"; \
		   $(MAKE) phase1 AWS_PROFILE=$$selected_profile AWS_REGION=$$selected_region ;; \
		4) echo "$(BLUE)🚀 Phase 2: ETL + Prerequisites$(NC)"; \
		   $(MAKE) phase2 AWS_PROFILE=$$selected_profile AWS_REGION=$$selected_region ;; \
		5) echo "$(BLUE)🚀 Phase 3: Generate Data$(NC)"; \
		   $(MAKE) phase3 AWS_PROFILE=$$selected_profile AWS_REGION=$$selected_region ;; \
		6) echo "$(BLUE)🚀 Phase 4: QuickSight Dashboard$(NC)"; \
		   $(MAKE) phase4 AWS_PROFILE=$$selected_profile AWS_REGION=$$selected_region ;; \
		7) echo "$(BLUE)🚀 Phase 5: Bedrock Agent$(NC)"; \
		   $(MAKE) phase5 AWS_PROFILE=$$selected_profile AWS_REGION=$$selected_region ;; \
		*) echo "$(RED)❌ Invalid deployment option$(NC)"; exit 1 ;; \
	esac

install: ## Install dependencies
	@echo "$(GREEN)Installing dependencies...$(NC)"
	cd deployment/cdk && npm install
	cd source/synthetic-data && pip3 install -r requirements.txt --break-system-packages
	@echo "$(GREEN)✓ Done$(NC)"

bootstrap: ## Bootstrap CDK
	@echo "$(GREEN)Bootstrapping CDK...$(NC)"
	cd deployment/cdk && \
		AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=$(AWS_REGION) \
		cdk bootstrap
	@echo "$(GREEN)✓ Done$(NC)"

phase1: ## Deploy data lake
	@echo "$(GREEN)Phase 1: Deploying data lake...$(NC)"
	@echo "$(BLUE)Using: Profile=$(AWS_PROFILE), Region=$(AWS_REGION)$(NC)"
	cd deployment/cdk && \
		AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=$(AWS_REGION) \
		cdk deploy $(STACK_PREFIX)-data-lake $(STACK_PREFIX)-glue $(STACK_PREFIX)-athena \
		--require-approval never
	@echo "$(GREEN)✓ Phase 1 complete$(NC)"

phase2: ## Deploy ETL
	@echo "$(GREEN)Phase 2: Deploying ETL...$(NC)"
	cd deployment/cdk && \
		AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=$(AWS_REGION) \
		cdk deploy $(STACK_PREFIX)-etl --require-approval never
	@echo ""
	@echo "$(GREEN)Setting up prerequisites...$(NC)"
	@cd deployment/scripts && ./setup-prerequisites.sh
	@echo "$(GREEN)✓ Phase 2 complete$(NC)"

phase3: ## Generate data
	@echo "$(GREEN)Phase 3: Generating $(CUSTOMER_COUNT) customers...$(NC)"
	@BUCKET=$$(aws cloudformation describe-stacks \
		--stack-name $(STACK_PREFIX)-data-lake \
		--query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' \
		--output text \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION) 2>/dev/null || echo "automotive-cx-data-lake-$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text)"); \
	echo "Using bucket: $$BUCKET"; \
	cd source/synthetic-data && \
		python3 generate_s3_data.py \
		--customers $(CUSTOMER_COUNT) \
		--bucket $$BUCKET \
		--profile $(AWS_PROFILE)
	@echo ""
	@echo "$(GREEN)Ensuring cx_analytics database exists...$(NC)"
	@aws glue create-database \
		--database-input '{"Name":"cx_analytics","Description":"Customer 360 Analytics"}' \
		--region $(AWS_REGION) \
		--profile $(AWS_PROFILE) 2>/dev/null || echo "$(YELLOW)Database already exists$(NC)"
	@echo ""
	@echo "$(GREEN)Creating Athena tables and views...$(NC)"
	@BUCKET=$$(aws cloudformation describe-stacks \
		--stack-name $(STACK_PREFIX)-data-lake \
		--query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' \
		--output text \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION) 2>/dev/null || echo "automotive-cx-data-lake-$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text)"); \
	source/scripts/create_athena_tables.sh $$BUCKET $(AWS_PROFILE) $(AWS_REGION)
	@echo "$(GREEN)✓ Phase 3 complete$(NC)"

phase4: ## Deploy QuickSight dashboards
	@echo "$(GREEN)Phase 4: Setting up QuickSight...$(NC)"
	@echo ""
	@echo "$(GREEN)Creating QuickSight datasets...$(NC)"
	@AWS_REGION=$(AWS_REGION) AWS_PROFILE=$(AWS_PROFILE) cd deployment/scripts && python3 update_quicksight_datasets.py
	@echo ""
	@echo "$(GREEN)Importing dashboard...$(NC)"
	@AWS_REGION=$(AWS_REGION) AWS_PROFILE=$(AWS_PROFILE) cd deployment/scripts && python3 import_dashboard.py
	@echo ""
	@echo "$(GREEN)Creating QuickSight users...$(NC)"
	@AWS_REGION=$(AWS_REGION) AWS_PROFILE=$(AWS_PROFILE) cd deployment/scripts && python3 create_quicksight_users.py
	@echo "$(GREEN)✓ Phase 4 complete$(NC)"

phase5: ## Deploy Bedrock agents
	@echo "$(GREEN)Phase 5: Deploying Aurora PostgreSQL with pgvector...$(NC)"
	@cd deployment/cdk && \
		AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=$(AWS_REGION) \
		cdk deploy $(STACK_PREFIX)-aurora --require-approval never
	@echo ""
	@echo "$(GREEN)Initializing pgvector extension...$(NC)"
	@CLUSTER_ARN=$$(aws rds describe-db-clusters \
		--query 'DBClusters[?starts_with(DBClusterIdentifier, `cx360-$(DEPLOYMENT_STAGE)-aurora`)].DBClusterArn' \
		--output text \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION)); \
	SECRET_ARN=$$(aws cloudformation describe-stacks \
		--stack-name $(STACK_PREFIX)-aurora \
		--query 'Stacks[0].Outputs[?OutputKey==`SecretArn`].OutputValue' \
		--output text \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION)); \
	cd deployment/scripts && ./init-aurora-pgvector-rds-api.sh $$CLUSTER_ARN $$SECRET_ARN
	@echo ""
	@echo "$(GREEN)Creating Bedrock Knowledge Base (via CLI)...$(NC)"
	@cd deployment/scripts && ./create-bedrock-kb-cli.sh
	@echo ""
	@echo "$(GREEN)Creating Bedrock Agent...$(NC)"
	@cd deployment/scripts && ./create-bedrock-agent-cli.sh
	@echo "$(GREEN)✓ Phase 5 complete$(NC)"

deploy-all: install phase1 phase2 phase3 phase4 phase5 ## Deploy everything
	@echo ""
	@echo "$(GREEN)========================================$(NC)"
	@echo "$(GREEN)✓ Deployment Complete!$(NC)"
	@echo "$(GREEN)========================================$(NC)"
	@echo ""
	@echo "Run: make verify"

verify: ## Verify deployment
	@echo "$(GREEN)Verifying deployment...$(NC)"
	@aws glue get-database --name cx_analytics \
		--profile $(AWS_PROFILE) --region $(AWS_REGION) \
		> /dev/null && echo "  ✓ Glue database exists"
	@TABLE_COUNT=$$(aws glue get-tables \
		--database-name cx_analytics \
		--profile $(AWS_PROFILE) --region $(AWS_REGION) \
		--query 'length(TableList)' --output text); \
	echo "  ✓ Found $$TABLE_COUNT tables"

clean: ## Delete all resources
	@echo "$(YELLOW)⚠️  WARNING: This will delete ALL Customer 360 resources!$(NC)"
	@echo ""
	@echo "This will remove:"
	@echo "  - All CloudFormation stacks (cx360-*)"
	@echo "  - S3 buckets and data"
	@echo "  - Glue database and tables"
	@echo "  - Athena workgroup"
	@echo "  - QuickSight dashboards and datasets"
	@echo "  - Bedrock Agent"
	@echo ""
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		echo "$(BLUE)Cleaning up resources...$(NC)"; \
		echo ""; \
		echo "$(GREEN)Deleting QuickSight resources...$(NC)"; \
		ACCOUNT_ID=$$(aws sts get-caller-identity --query Account --output text --profile $(AWS_PROFILE)); \
		aws quicksight delete-dashboard --aws-account-id $$ACCOUNT_ID --dashboard-id customer-360-dashboard --region $(AWS_REGION) --profile $(AWS_PROFILE) 2>/dev/null || true; \
		aws quicksight delete-analysis --aws-account-id $$ACCOUNT_ID --analysis-id customer-360-analysis --region $(AWS_REGION) --profile $(AWS_PROFILE) 2>/dev/null || true; \
		for ds in kpi-trends operational-kpis customer-health-scores at-risk-revenue customer-360 issue-categories revenue-breakdown top-revenue-stream; do \
			aws quicksight delete-data-set --aws-account-id $$ACCOUNT_ID --data-set-id $$ds --region $(AWS_REGION) --profile $(AWS_PROFILE) 2>/dev/null || true; \
		done; \
		echo "$(GREEN)Deleting Glue crawler...$(NC)"; \
		aws glue delete-crawler --name cx-analytics-crawler --region $(AWS_REGION) --profile $(AWS_PROFILE) 2>/dev/null || true; \
		echo "$(GREEN)Destroying CDK stacks...$(NC)"; \
		cd deployment/cdk && \
			AWS_PROFILE=$(AWS_PROFILE) AWS_REGION=$(AWS_REGION) \
			cdk destroy --all --force; \
		echo "$(GREEN)Deleting S3 buckets...$(NC)"; \
		BUCKET=$$(aws cloudformation describe-stacks --stack-name cx360-$(DEPLOYMENT_STAGE)-data-lake --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null); \
		if [ -n "$$BUCKET" ]; then \
			aws s3 rm s3://$$BUCKET --recursive --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || true; \
			aws s3 rb s3://$$BUCKET --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || true; \
		fi; \
		echo "$(GREEN)✓ Cleanup complete$(NC)"; \
	fi
