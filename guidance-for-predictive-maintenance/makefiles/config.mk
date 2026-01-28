# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# ========================================================
# AWS CONFIGURATION
# ========================================================
# DEFAULTS.AWS_ACCOUNT_ID := $(shell aws sts get-caller-identity --query "Account" --output text)
# DEFAULTS.AWS_REGION := $(shell aws configure get region --output text)

# export AWS_ACCOUNT_ID ?= ${DEFAULTS.AWS_ACCOUNT_ID}
# export AWS_REGION ?= ${DEFAULTS.AWS_REGION}

# ========================================================
# SOLUTION METADATA
# ========================================================
export SOLUTION_NAME ?= mmt-predictive-maintenance
export SOLUTION_DESCRIPTION ?= Predictive Maintenance Solution for MMT
export SOLUTION_VERSION ?= v1.0.0
export SOLUTION_AUTHOR = AWS Industrial Solutions Team
export SOLUTION_ID = SO0000
# Path is relative to this file's location, moving this file requires updating this path.
export SOLUTION_PATH := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../)
export APPLICATION_TYPE = AWS-Solutions

# ========================================================
# ENVIRONMENT CONFIGURATION
# ========================================================
DEFAULTS.NODE_VERSION := $(shell cat .nvmrc 2> /dev/null)
DEFAULTS.PYTHON_VERSION := $(shell cat .python-version)

export NODE_VERSION ?= ${DEFAULTS.NODE_VERSION}
export PYTHON_VERSION ?= ${DEFAULTS.PYTHON_VERSION}

export PYTHON_MINIMUM_VERSION_SUPPORTED = 3.12
export LANG = en_US.UTF-8

# ========================================================
# VARIABLES
# ========================================================

# ==================================================================================
# PRINT COLORS
# 	To use: printf "%b<text>%b" "${<COLOR>}" "${NC}"
#   printf is recommended over echo if wanting color because of more multi-platform support.
#   https://en.wikipedia.org/wiki/ANSI_escape_code#Colors
#
# COLOR USAGE
# 	MAGENTA: Start, Progress, etc.
# 	RED: Failure, Stop, Cancel, Error, etc.
# 	GREEN: Success, Finished, Done, etc.
# 	YELLOW: Relevant extra prints or notes
# 	CYAN: Emphasis within a print or note. Links, commands, paths, etc. Typically combined with YELLOW
#	NC: No Color. Only use to end color, otherwise use nothing.
# ==================================================================================
export MAGENTA = \033[0;35m
export RED = \033[0;31m
export GREEN = \033[0;32m
export YELLOW = \033[0;33m
export CYAN = \033[0;36m
export NC = \033[00m
