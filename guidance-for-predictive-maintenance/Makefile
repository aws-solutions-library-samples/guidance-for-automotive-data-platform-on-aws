# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

.DEFAULT_GOAL := help
SHELL := /bin/bash

DEFAULTS.NODE_VERSION := $(shell cat .nvmrc 2> /dev/null)
DEFAULTS.PYTHON_VERSION := $(shell cat .python-version)

NODE_VERSION ?= ${DEFAULTS.NODE_VERSION}
PYTHON_VERSION ?= ${DEFAULTS.PYTHON_VERSION}

include makefiles/config.mk
include makefiles/targets.mk

export STACK_NAME ?= dev-mmt-predictive-maintenance
export STACK_TEMPLATE_NAME = template.json
export STACK_TEMPLATE_PATH ?= deployment/global-s3-assets/${STACK_TEMPLATE_NAME}

.PHONY: upgrade
upgrade: verify-required-tools ## Upgrades all lock files without installing dependencies.
	@printf "%b\nUpgrading all lock files.%b\n" "${MAGENTA}" "${NC}"
	poetry lock -C ./source/infrastructure
	@printf "%b\nFinished upgrading lock files.%b\n" "${GREEN}" "${NC}"
	@printf "%bRun %b\"make install\"%b to install upgraded dependencies.%b\n" "${YELLOW}" "${CYAN}" "${YELLOW}" "${NC}"

.PHONY: install
install: verify-required-tools ## Installs all dependencies needed to build the solution.
	@printf "%b\nInstalling dependencies from all lock files.%b\n" "${MAGENTA}" "${NC}"
	@printf "%bTo instead upgrade lock files and node dependencies, run %b\"make upgrade\"%b first.%b\n" "${YELLOW}" "${CYAN}" "${YELLOW}" "${NC}"
	poetry install
	poetry install -C ./source/infrastructure
	@printf "%b\nFinished installing dependencies from lock files.%b\n" "${GREEN}" "${NC}"

.PHONY: create-rc-file
create-rc-file: ## Create rc file for environment variables which are likely to be customized. Default values provided where possible.
	@printf "TODO: NOT YET IMPLEMENTED. SOLUTION DEPLOYMENT CONFIG NOT YET ESTABLISHED."

.PHONY: build
build: ## Builds the solution, copies assets to the deployment folder.
	@printf "%bBuilding solution.%b\n" "${MAGENTA}" "${NC}"
	@./deployment/build-s3-dist.sh
	@printf "%b\nFinished build.%b\n" "${GREEN}" "${NC}"
	@printf "%b\nSee %b\"./deployment/global-s3-assets\"%b and %b\"./deployment/regional-s3-assets\"%b for built assets.%b\n" "${YELLOW}" "${CYAN}" "${YELLOW}" "${CYAN}" "${YELLOW}" "${NC}"
	@printf "%bRun %b\"make deploy\"%b to deploy the solution.%b\n" "${YELLOW}" "${CYAN}" "${YELLOW}" "${NC}"

.PHONY: deploy
deploy: ## Deploy the solution.
	@printf "%bStarting deploy.%b\n" "${MAGENTA}" "${NC}"
	poetry -C ./source/infrastructure run cdk deploy --require-approval never
	@printf "%b\nFinished deploy.%b\n" "${GREEN}" "${NC}"

.PHONY: destroy
destroy: ## Tear down deployed resources.
	@printf "%bStarting destroy.%b\n" "${MAGENTA}" "${NC}"
	poetry -C ./source/infrastructure run cdk destroy --force
	@printf "%b\nFinished destroy.%b\n" "${GREEN}" "${NC}"

.PHONY: test
test:  ## Run unit-tests.
	@printf "TODO: NOT YET IMPLEMENTED. SOLUTION TESTS NOT FULLY ESTABLISHED."

.PHONY: update-snapshots
update-snapshots:  ## Run update-snapshots.
	@printf "TODO: NOT YET IMPLEMENTED."

.PHONY: pre-commit
pre-commit: ## Run pre-commit for all files.
	@printf "%bRunning pre-commit for all files.%b\n" "${MAGENTA}" "${NC}"
	poetry run pre-commit run --all-files

## ========================================================
## HELPERS
## ========================================================
.PHONY: help
help: ## Displays this help message.
	@grep -E '^[a-zA-Z0-9 -_]+:.*##|^##.*'  ${SOLUTION_PATH}/Makefile | while read -r l; \
	do ( [[ "$$l" =~ ^"##" ]] && printf "%b%s%b\n" "${MAGENTA}" "$$(echo $$l | cut -f 2- -d' ')" "${NC}") \
	|| ( printf "%b%-35s%s%b\n" "${GREEN}" "$$(echo $$l | cut -f 1 -d':')" "$$(echo $$l | cut -f 3- -d'#')" "${NC}"); \
	done;

.PHONY: encourage
encourage: ## Sometimes we all need a little encouragement!
	@printf "%bYou can do this. Believe in yourself. :)%b\n" "${GREEN}" "${NC}"

.PHONY: root-version
root-version: ## Display solution name and current version
	@printf "%b%35.35s%b version:%b%s%b\n" "${MAGENTA}" "${SOLUTION_NAME}" "${NC}" "${GREEN}" "${SOLUTION_VERSION}" "${NC}"
