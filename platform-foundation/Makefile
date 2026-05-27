.PHONY: help deploy deploy-network deploy-domain verify clean status

# Colors
GREEN  := \033[0;32m
YELLOW := \033[1;33m
NC     := \033[0m

# Configuration
AWS_REGION ?= us-east-1
AWS_PROFILE ?= default
STACK_NAME := automotive-data-platform-network
DOMAIN_NAME := automotive-data-platform

help: ## Show this help message
	@echo "$(GREEN)Automotive Data Platform - Deployment Commands$(NC)"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "Environment Variables:"
	@echo "  AWS_REGION         = $(AWS_REGION)"
	@echo "  AWS_PROFILE        = $(AWS_PROFILE)"
	@echo "  DEFAULT_USERNAME   = Username for SSO user (default: admin)"
	@echo "  DEFAULT_EMAIL      = Email for SSO user (default: admin@example.com)"

deploy: ## Deploy complete platform (infrastructure + domain + blueprints)
	@echo "$(GREEN)Deploying complete Automotive Data Platform...$(NC)"
	@chmod +x deployment/deploy-complete-platform.sh
	@./deployment/deploy-complete-platform.sh

publish-data: ## Publish data sources to DataZone catalog (run after catalog project environments are ACTIVE)
	@echo "$(GREEN)Publishing data sources to DataZone...$(NC)"
	@chmod +x scripts/publish-data-sources.sh
	@./scripts/publish-data-sources.sh

deploy-shared: ## Deploy shared resources (S3 bucket, Glue database)
	@./deployment/deploy-shared-resources.sh

deploy-all: deploy deploy-shared deploy-tire-project ## Deploy complete platform (domain + shared resources + tire project)

deploy-full: ## Deploy complete platform (network + domain + user)
	@echo "$(GREEN)Deploying complete Automotive Data Platform...$(NC)"
	@echo "$(GREEN)Step 1/3: Network infrastructure...$(NC)"
	@./deployment/deploy-base-platform.sh
	@echo ""
	@echo "$(GREEN)Step 2/3: DataZone domain...$(NC)"
	@./deployment/deploy-datazone-simple.sh
	@echo ""
	@echo "$(GREEN)Deployment complete!$(NC)"

deploy-network: ## Deploy base network infrastructure only
	@echo "$(GREEN)Deploying base network infrastructure...$(NC)"
	@./deployment/deploy-base-platform.sh

deploy-domain: ## Create SageMaker Unified Studio domain
	@echo "$(GREEN)Creating SageMaker Unified Studio domain...$(NC)"
	@./deployment/create-sagemaker-domain.sh
	@echo ""
	@echo "$(GREEN)Creating default user profile...$(NC)"
	@./deployment/create-user-profile.sh

create-user: ## Create additional user profile (usage: make create-user DEFAULT_USERNAME=username DEFAULT_EMAIL=user@example.com)
	@./deployment/create-user-profile.sh || echo "User profile creation skipped"
	@DEFAULT_EMAIL=$(DEFAULT_EMAIL) ./deployment/setup-sso-permissions.sh
	@DEFAULT_EMAIL=$(DEFAULT_EMAIL) ./deployment/add-domain-owner.sh

verify: ## Verify deployment status
	@echo "$(GREEN)Verifying deployment...$(NC)"
	@echo ""
	@echo "CloudFormation Stack:"
	@aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		--region $(AWS_REGION) \
		--profile $(AWS_PROFILE) \
		--query 'Stacks[0].[StackName,StackStatus]' \
		--output table || echo "Stack not found"
	@echo ""
	@echo "VPC:"
	@if [ -f deployment/stack-outputs.env ]; then \
		source deployment/stack-outputs.env && \
		aws ec2 describe-vpcs \
			--vpc-ids $$VPC_ID \
			--region $(AWS_REGION) \
			--profile $(AWS_PROFILE) \
			--query 'Vpcs[0].[VpcId,State,CidrBlock]' \
			--output table 2>/dev/null || echo "VPC not found"; \
	else \
		echo "Stack outputs not found. Run 'make deploy-network' first"; \
	fi
	@echo ""
	@echo "SageMaker Domain:"
	@if [ -f deployment/stack-outputs.env ]; then \
		source deployment/stack-outputs.env && \
		if [ -n "$$DOMAIN_ID" ]; then \
			aws sagemaker describe-domain \
				--domain-id $$DOMAIN_ID \
				--region $(AWS_REGION) \
				--profile $(AWS_PROFILE) \
				--query '[DomainId,Status,Url]' \
				--output table 2>/dev/null || echo "Domain not found"; \
		else \
			echo "Domain not created yet. Run 'make deploy-domain'"; \
		fi; \
	fi

status: ## Show deployment status and outputs
	@echo "$(GREEN)Deployment Status$(NC)"
	@echo ""
	@if [ -f deployment/stack-outputs.env ]; then \
		source deployment/stack-outputs.env && \
		echo "VPC ID:        $$VPC_ID" && \
		echo "Stack Name:    $$STACK_NAME" && \
		echo "Region:        $$AWS_REGION" && \
		echo "Domain ID:     $$DOMAIN_ID" && \
		echo "Portal URL:    $$DOMAIN_URL" && \
		echo "" && \
		if [ -f deployment/user-credentials.txt ]; then \
			echo "$(GREEN)User Credentials:$(NC)" && \
			cat deployment/user-credentials.txt; \
		fi; \
	else \
		echo "$(YELLOW)No deployment found. Run 'make deploy' to get started.$(NC)"; \
	fi

outputs: ## Display stack outputs
	@if [ -f deployment/stack-outputs.env ]; then \
		cat deployment/stack-outputs.env; \
	else \
		echo "$(YELLOW)No outputs found. Deploy infrastructure first.$(NC)"; \
	fi

clean: ## Delete all deployed resources
	@echo "$(YELLOW)WARNING: This will delete all platform resources!$(NC)"
	@read -p "Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ] || exit 1
	@chmod +x deployment/cleanup-domain.sh
	@./deployment/cleanup-domain.sh
	@rm -f /tmp/automotive-platform/config.env
	@echo "$(GREEN)Cleanup initiated!$(NC)"

logs: ## Show CloudFormation stack events
	@aws cloudformation describe-stack-events \
		--stack-name $(STACK_NAME) \
		--region $(AWS_REGION) \
		--profile $(AWS_PROFILE) \
		--max-items 20 \
		--query 'StackEvents[*].[Timestamp,ResourceStatus,ResourceType,LogicalResourceId]' \
		--output table

cost: ## Estimate monthly costs
	@echo "$(GREEN)Estimated Monthly Costs$(NC)"
	@echo ""
	@echo "Base Platform:"
	@echo "  NAT Gateway:        \$$32.00"
	@echo "  VPC Endpoints:      \$$36.00"
	@echo "  CloudWatch Logs:    \$$2.50"
	@echo "  Data Transfer:      \$$13.50"
	@echo "  ─────────────────────────"
	@echo "  Total:              ~\$$84.00/month"
	@echo ""
	@echo "Note: Project-specific costs (compute, storage) are additional"

datazone-login: ## Get IAM portal login URL for DataZone
	@if [ -f deployment/datazone-outputs.env ]; then \
		source deployment/datazone-outputs.env && \
		echo "$(GREEN)Getting portal login URL...$(NC)" && \
		aws datazone get-iam-portal-login-url --domain-identifier $$DOMAIN_ID --region $$REGION --query 'authCodeUrl' --output text; \
	else \
		echo "$(YELLOW)DataZone not deployed. Run 'make deploy' first.$(NC)"; \
	fi

datazone-status: ## Show DataZone domain status
	@if [ -f deployment/datazone-outputs.env ]; then \
		source deployment/datazone-outputs.env && \
		echo "$(GREEN)DataZone Domain Status$(NC)" && \
		echo "" && \
		aws datazone get-domain --identifier $$DOMAIN_ID --region $$REGION --query '{ID:id,Name:name,Status:status,Version:domainVersion,Portal:portalUrl}' --output table; \
	else \
		echo "$(YELLOW)DataZone not deployed. Run 'make deploy' first.$(NC)"; \
	fi

datazone-add-user: ## Add SSO user to DataZone (usage: make datazone-add-user EMAIL=user@example.com)
	@./deployment/add-sso-user.sh $(EMAIL)

deploy-tire-project: ## Deploy tire prediction ML project
	@./deployment/deploy-tire-prediction-project.sh

datazone-clean: ## Delete DataZone domain
	@if [ -f deployment/datazone-outputs.env ]; then \
		source deployment/datazone-outputs.env && \
		echo "$(YELLOW)Deleting DataZone domain $$DOMAIN_ID...$(NC)" && \
		aws datazone delete-domain --identifier $$DOMAIN_ID --region $$REGION && \
		echo "Waiting for deletion..." && \
		sleep 30 && \
		rm -f deployment/datazone-outputs.env && \
		echo "$(GREEN)Domain deleted$(NC)"; \
	else \
		echo "$(YELLOW)No DataZone domain found.$(NC)"; \
	fi

docs: ## Open documentation
	@echo "$(GREEN)Opening documentation...$(NC)"
	@open README.md || cat README.md

quickstart: ## Show quick start guide
	@cat QUICKSTART.md

.DEFAULT_GOAL := help
