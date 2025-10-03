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
	@echo "  AWS_REGION  = $(AWS_REGION)"
	@echo "  AWS_PROFILE = $(AWS_PROFILE)"

deploy: ## Deploy complete platform (network + domain)
	@echo "$(GREEN)Deploying complete Automotive Data Platform...$(NC)"
	@./deployment/deploy-complete-platform.sh

deploy-network: ## Deploy base network infrastructure only
	@echo "$(GREEN)Deploying base network infrastructure...$(NC)"
	@./deployment/deploy-base-platform.sh

deploy-domain: ## Create SageMaker Unified Studio domain
	@echo "$(GREEN)Creating SageMaker Unified Studio domain...$(NC)"
	@./deployment/create-sagemaker-domain.sh

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
		echo "Portal URL:    $$DOMAIN_URL"; \
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
	@echo "$(GREEN)Deleting SageMaker domain...$(NC)"
	@if [ -f deployment/stack-outputs.env ]; then \
		source deployment/stack-outputs.env && \
		if [ -n "$$DOMAIN_ID" ]; then \
			aws sagemaker delete-domain \
				--domain-id $$DOMAIN_ID \
				--region $(AWS_REGION) \
				--profile $(AWS_PROFILE) 2>/dev/null || true; \
			echo "Waiting for domain deletion..."; \
			sleep 30; \
		fi; \
	fi
	@echo "$(GREEN)Deleting CloudFormation stack...$(NC)"
	@aws cloudformation delete-stack \
		--stack-name $(STACK_NAME) \
		--region $(AWS_REGION) \
		--profile $(AWS_PROFILE)
	@echo "$(YELLOW)Waiting for stack deletion (this may take 5-10 minutes)...$(NC)"
	@aws cloudformation wait stack-delete-complete \
		--stack-name $(STACK_NAME) \
		--region $(AWS_REGION) \
		--profile $(AWS_PROFILE)
	@rm -f deployment/stack-outputs.env
	@echo "$(GREEN)Cleanup complete!$(NC)"

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

docs: ## Open documentation
	@echo "$(GREEN)Opening documentation...$(NC)"
	@open README.md || cat README.md

quickstart: ## Show quick start guide
	@cat QUICKSTART.md

.DEFAULT_GOAL := help
