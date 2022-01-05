# Copyright 2022 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import subprocess

import pytest


def test_post_process():
    """
    Test and verify that the output of the post_process step in the statistics
    generator stays consistent through updates to the gitdm module
    """
    # ./statistics-generator --repo 2.5.0..2.6.0
    prerendered_output = """### Statistics

A total of 2864 lines added, 1149 removed (delta 1715)

| Developers with the most changesets | |
|---|---|
| Fabio Tranchitella | 43 (42.2%) |
| Lluis Campos | 18 (17.6%) |
| Kristian Amlie | 18 (17.6%) |
| Alf-Rune Siqveland | 7 (6.9%) |
| Marcin Chalczynski | 7 (6.9%) |
| Krzysztof Jaskiewicz | 4 (3.9%) |
| Peter Grzybowski | 3 (2.9%) |
| Ole Petter Orhagen | 2 (2.0%) |

| Developers with the most changed lines | |
|---|---|
| Fabio Tranchitella | 1140 (37.7%) |
| Kristian Amlie | 686 (22.7%) |
| Marcin Chalczynski | 623 (20.6%) |
| Lluis Campos | 253 (8.4%) |
| Krzysztof Jaskiewicz | 96 (3.2%) |
| Ole Petter Orhagen | 86 (2.8%) |
| Alf-Rune Siqveland | 78 (2.6%) |
| Peter Grzybowski | 59 (2.0%) |

| Developers with the most lines removed | |
|---|---|

| Developers with the most signoffs (total 0) | |
|---|---|

| Developers with the most reviews (total 0) | |
|---|---|

| Developers with the most test credits (total 0) | |
|---|---|

| Developers who gave the most tested-by credits (total 0) | |
|---|---|

| Developers with the most report credits (total 0) | |
|---|---|

| Developers who gave the most report credits (total 0) | |
|---|---|

| Top changeset contributors by employer | |
|---|---|
| Northern.tech | 91 (89.2%) |
| RnDity | 11 (10.8%) |

| Top lines changed by employer | |
|---|---|
| Northern.tech | 2302 (76.2%) |
| RnDity | 719 (23.8%) |

| Employers with the most signoffs (total 0) | |
|---|---|

| Employers with the most hackers (total 8) | |
|---|---|
| Northern.tech | 6 (75.0%) |
| RnDity | 2 (25.0%) |
"""
    # Run the statistics_generator on the range (mender-client 2.5.0..2.6.0)
    # and compare it to the prerendered output. If the output has changed, be
    # vary with updating the gitdm module.
    try:
        updated_rendered_output = subprocess.check_output(
            ["./extra/statistics-generator", "--repo", "2.5.0..2.6.0",]
        )
        assert (
            updated_rendered_output.decode("utf-8") == prerendered_output
        ), "It seems the rendered Changelog has changed it's default look"
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Got Process error: {e}")
