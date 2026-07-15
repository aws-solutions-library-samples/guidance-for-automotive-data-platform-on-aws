.PHONY: deploy destroy synth bootstrap help

DEPLOYMENT_STAGE ?= dev
AWS_REGION ?= $(shell aws configure get region 2>/dev/null || echo "us-west-2")
AWS_PROFILE ?= default

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Bootstrap CDK in the target account/region
	@source .venv/bin/activate 2>/dev/null || (python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt)
	@cdk bootstrap aws://$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text)/$(AWS_REGION) --profile $(AWS_PROFILE)

synth: ## Synthesize CloudFormation template
	@source .venv/bin/activate && \
	CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text) \
	CDK_DEFAULT_REGION=$(AWS_REGION) \
	DEPLOYMENT_STAGE=$(DEPLOYMENT_STAGE) \
	cdk synth

deploy: ## Deploy the telemetry fanout service
	@echo "Deploying telemetry fanout (stage=$(DEPLOYMENT_STAGE), region=$(AWS_REGION))"
	@source .venv/bin/activate 2>/dev/null || (python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt)
	@source .venv/bin/activate && \
	CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text) \
	CDK_DEFAULT_REGION=$(AWS_REGION) \
	AWS_DEFAULT_REGION=$(AWS_REGION) \
	DEPLOYMENT_STAGE=$(DEPLOYMENT_STAGE) \
	cdk deploy --all --require-approval never --profile $(AWS_PROFILE)
	@echo ""
	@echo "Post-deploy: Set BOOTSTRAP_SERVERS on the Fargate task"
	@MSK_ARN=$$(aws cloudformation describe-stacks --stack-name cms-$(DEPLOYMENT_STAGE)-msk \
		--query "Stacks[0].Outputs[?OutputKey=='MSKClusterArn'].OutputValue" \
		--output text --region $(AWS_REGION) --profile $(AWS_PROFILE)); \
	BOOTSTRAP=$$(aws kafka get-bootstrap-brokers --cluster-arn $$MSK_ARN \
		--query 'BootstrapBrokerStringSaslIam' --output text --region $(AWS_REGION) --profile $(AWS_PROFILE)); \
	echo "BOOTSTRAP_SERVERS=$$BOOTSTRAP"

destroy: ## Destroy the telemetry fanout service
	@source .venv/bin/activate && \
	CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text) \
	CDK_DEFAULT_REGION=$(AWS_REGION) \
	AWS_DEFAULT_REGION=$(AWS_REGION) \
	DEPLOYMENT_STAGE=$(DEPLOYMENT_STAGE) \
	cdk destroy --all --force --profile $(AWS_PROFILE)
