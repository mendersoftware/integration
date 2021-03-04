#!/usr/bin/env python3
# Copyright 2021 Northern.tech AS
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

import os
import requests
import argparse

GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN")
if GITLAB_TOKEN is None:
    raise RuntimeError("provide the GITLAB_TOKEN variable!")

# not every var is interesting for local dev
DEV_VARS = ["STRIPE_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID"]


def main(args):
    v = get_gitlab_vars(GITLAB_TOKEN)
    if args.all:
        f = format_vars(v)
    else:
        f = format_vars(v, DEV_VARS)

    print(f)


def get_gitlab_vars(token):
    res = requests.get(
        # project id = mender-qa
        "https://gitlab.com/api/v4/projects/12501706/variables",
        headers={"PRIVATE-TOKEN": token},
    )
    if res.status_code != 200:
        msg = "http {} \n{}".format(res.status_code, res.json())
        raise RuntimeError("gitlab request failed: \n{}".format(msg))

    return res.json()


def format_vars(json, names=None):
    selected = json

    if names is not None:
        selected = [x for x in json if x["key"] in names]

    s = ""
    for v in selected:
        s += "{}={}\n".format(v["key"], v["value"])
    return s


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pull and dump interesting env vars from gitlab - ready for sourcing for your local test runs:\n\n"
        "GITLAB_TOKEN=<your gitlab access token> ./dump-gitlab-env.py\n\n"
        + "(see: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--all",
        default=False,
        action="store_true",
        help="grab the full set of env vars (many are irrelevant to local dev though!)",
    )

    args = parser.parse_args()

    main(args)
