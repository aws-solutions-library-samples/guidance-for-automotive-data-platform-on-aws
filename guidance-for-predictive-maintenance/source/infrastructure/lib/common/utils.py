# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
from dataclasses import dataclass


@dataclass(frozen=True)
class SolutionConfigInputs:
    solution_name: str
    solution_id: str
    solution_version: str

    def get_user_agent_string(self) -> str:
        return f"AWSSOLUTION/{self.solution_id}/{self.solution_version}"
