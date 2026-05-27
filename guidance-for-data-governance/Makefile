.PHONY: deploy destroy synth help

DEPLOYMENT_STAGE ?= dev
AWS_REGION ?= $(shell aws configure get region 2>/dev/null || echo "eu-west-1")
AWS_PROFILE ?= default

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

synth: ## Synthesize CloudFormation template
	@source .venv/bin/activate 2>/dev/null || (python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt)
	@source .venv/bin/activate && \
	CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text) \
	CDK_DEFAULT_REGION=$(AWS_REGION) \
	DEPLOYMENT_STAGE=$(DEPLOYMENT_STAGE) \
	cdk synth

deploy: ## Deploy the governance framework
	@echo "Deploying data governance (stage=$(DEPLOYMENT_STAGE), region=$(AWS_REGION))"
	@source .venv/bin/activate 2>/dev/null || (python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt)
	@source .venv/bin/activate && \
	CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text) \
	CDK_DEFAULT_REGION=$(AWS_REGION) \
	AWS_DEFAULT_REGION=$(AWS_REGION) \
	DEPLOYMENT_STAGE=$(DEPLOYMENT_STAGE) \
	cdk deploy --all --require-approval never --profile $(AWS_PROFILE)
	@echo "Post-deploy: Upload Glue ETL script"
	@aws s3 cp source/glue-jobs/anonymize_telemetry.py \
		s3://adp-$(DEPLOYMENT_STAGE)-anonymized-data-$$(aws sts get-caller-identity --query Account --output text)-$(AWS_REGION)/scripts/ \
		--region $(AWS_REGION) --profile $(AWS_PROFILE)
	@echo "Done"

destroy: ## Destroy the governance framework
	@source .venv/bin/activate && \
	CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text) \
	CDK_DEFAULT_REGION=$(AWS_REGION) \
	AWS_DEFAULT_REGION=$(AWS_REGION) \
	DEPLOYMENT_STAGE=$(DEPLOYMENT_STAGE) \
	cdk destroy --all --force --profile $(AWS_PROFILE)
