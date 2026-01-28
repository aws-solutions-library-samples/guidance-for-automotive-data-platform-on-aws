# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.

.PHONY: verify-required-tools
verify-required-tools: ## Checks the environment for the required dependencies.
	@[ "Python ${PYTHON_VERSION}" = "$$(python --version | cut -d "." -f 1-2)" ] || ( printf "%bPython version %s is required, as specified in .python-version. %s was found instead. Please install the correct version by running 'pyenv install -s'%b\n" "${RED}" "Python ${PYTHON_VERSION}" "$(shell python --version | cut -d "." -f 1-2)" "${NC}"; sh -c 'exit 1' )
	@[ $$(which poetry) ] || ( printf "%bpoetry is required, as specified in the README. Please see the following link for installation: https://python-poetry.org/docs/#installation%b\n" "${RED}" "${NC}"; sh -c 'exit 1' )
	@[ $$(which aws) ] || ( printf "%bThe aws CLI is required, as specified in the README. Please see the following link for installation: https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html%b\n" "${RED}" "${NC}"; sh -c 'exit 1' )
	@[ $$(which cdk) ] || ( printf "%bThe aws-cdk CLI is required, as specified in the README. Please see the following link for installation: https://docs.aws.amazon.com/cdk/v2/guide/cli.html%b\n" "${RED}" "${NC}"; sh -c 'exit 1' )
	@printf "%bDependencies verified.%b\n\n" "${GREEN}" "${NC}"
