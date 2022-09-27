#!/usr/bin/env python3
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

from argparse import Namespace
from calendar import isleap, monthrange
from collections import namedtuple
from contextlib import redirect_stdout
from datetime import datetime, time, timedelta
from io import StringIO
from os import getenv
from re import compile
import json

from release_tool import do_list_repos

Tag = namedtuple("Tag", ["version", "datetime"])
LtsEnd = namedtuple("LtsEnd", ["isExpired", "date"])

releaseMatcher = compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")
tagMatcher = compile(r"tag:'(.*)' datetime:'(\d+)'")

lastChecked = getenv("LAST_CHECKED", "2.2.0")
endOfToday = datetime.combine(datetime.now(), time.max)

ltsChecks = {
    # until 3.1 all even releases were LTS
    "until-3.2": lambda minorVersion, minorValue: minorVersion < "3.2"
    and not int(minorValue) % 2,
    # from 3.3 all odd releases are assumed to be LTS
    "from-3.3": lambda minorVersion, minorValue: minorVersion >= "3.2"
    and int(minorValue) % 2,
}


def determine_lts_end(tag, currentMinor, releases):
    match = releaseMatcher.match(f"{currentMinor}.0")
    if not any(
        map(lambda check: check(currentMinor, match.group(2)), ltsChecks.values())
    ):
        return
    aYear = timedelta(
        days=366
        if (
            (tag.datetime.month >= 3 and isleap(tag.datetime.year + 1))
            or (tag.datetime.month < 3 and isleap(tag.datetime.year))
        )
        else 365
    )
    expirationDate = tag.datetime + aYear
    if currentMinor in releases:
        eolDate = releases[currentMinor]["supported_until"].split("-")
        expirationDate = datetime.fromisoformat(
            f"{eolDate[0]}-{eolDate[1]}-{monthrange(int(eolDate[0]), int(eolDate[1]))[1]}T{str(time.max)}"
        )
    isExpired = expirationDate < endOfToday
    return LtsEnd(isExpired, expirationDate)


def collect_release_info(tag, minorRelease):
    args = {
        "list": "git",
        "list_format": "json",
        "in_integration_version": tag.version,
    }
    repoList = StringIO()
    with redirect_stdout(repoList):
        do_list_repos(
            Namespace(**args), False, False, False,
        )

    versionReposInfo = json.loads(repoList.getvalue())
    existingInfo = {}
    if tag.version in minorRelease:
        existingInfo = minorRelease[tag.version]
    result = {
        "release_date": tag.datetime.strftime("%Y-%m-%d"),
        **existingInfo,
        **versionReposInfo,
    }
    result["repos"] = list(filter(lambda repo: (repo["version"]), result["repos"]))
    return result


def get_releases():
    tags = []
    saasTags = []
    with open("tags", "r") as tagsFile:
        for line in tagsFile:
            tagMatch = tagMatcher.match(line.strip())
            if not tagMatch:
                continue
            tag = Tag(tagMatch.group(1), datetime.fromtimestamp(int(tagMatch.group(2))))
            if tag.version.startswith("saas"):
                saasTags.append(
                    {"tag": tag.version, "date": tag.datetime.strftime("%Y-%m-%d")}
                )
            match = releaseMatcher.fullmatch(tag.version)
            if match and tag.version >= lastChecked:
                tags.append(tag)
    return {"saasTags": saasTags, "tags": tags}


taggedReleases = get_releases()
releases = taggedReleases["tags"]
releaseInformation = {"lts": [], "releases": {}, "saas": taggedReleases["saasTags"]}

with open("versions.json", "r") as current:
    existingReleaseInformation = json.load(current)
    releaseInformation["releases"] = existingReleaseInformation["releases"]

ltsReleases = []
for release in releases:
    print(f"processing {release.version}")
    match = releaseMatcher.match(release.version)
    currentMinor = f"{match.group(1)}.{match.group(2)}"
    initialMinorRelease = next(
        (rel for rel in releases if rel.version == f"{currentMinor}.0"), release
    )
    ltsEnd = determine_lts_end(
        initialMinorRelease, currentMinor, releaseInformation["releases"]
    )
    if ltsEnd and not ltsEnd.isExpired and currentMinor not in ltsReleases:
        ltsReleases.append(currentMinor)
    if currentMinor not in releaseInformation["releases"]:
        releaseInformation["releases"][currentMinor] = {}
        if ltsEnd:
            releaseInformation["releases"][currentMinor][
                "supported_until"
            ] = ltsEnd.date.strftime("%Y-%m")
    releaseInformation["releases"][currentMinor][
        release.version
    ] = collect_release_info(release, releaseInformation["releases"][currentMinor])

releaseInformation["releases"] = dict(
    sorted(releaseInformation["releases"].items(), reverse=True)
)
releaseInformation["releases"] = {
    currentMinor: dict(
        sorted(releaseInformation["releases"][currentMinor].items(), reverse=True)
    )
    for currentMinor in releaseInformation["releases"].keys()
}

releaseInformation["lts"] = ltsReleases
with open("versions.json", "w") as result:
    json.dump(releaseInformation, result)
