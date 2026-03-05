#!/bin/bash
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

set -e

if [ -z "$GITHUB_TOKEN" ]; then
    echo "GITHUB_TOKEN not set"
    exit 1
fi

if [ -z $1 ]; then
    echo "usage: $0 integration-version"
    exit 1
fi

RELEASE_VERSION="$1"

release_tool=$(dirname "$0")/release_tool.py

rm -rf mender-${RELEASE_VERSION}-src
rm -f mender-${RELEASE_VERSION}-src.tar
mkdir mender-${RELEASE_VERSION}-src

for repo in $(${release_tool} --list); do
    repo_version=$(${release_tool} --version-of ${repo} --in-integration-version ${RELEASE_VERSION})
    url="https://api.github.com/repos/mendersoftware/${repo}/tarball/refs/tags/${repo_version}"
    echo "Getting $url ..."
    wget --header "Authorization: token ${GITHUB_TOKEN}" ${url}
    mv ${repo_version} mender-${RELEASE_VERSION}-src/${repo}-${repo_version}.tar.gz
done

echo
echo "Downloaded source tarballs:"
ls -1 mender-${RELEASE_VERSION}-src

echo
read -p "Remove source for OS repos that have Enterprise fork? " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    for repo_ent in $(ls mender-${RELEASE_VERSION}-src | egrep '\-enterprise.*tar.gz$'); do
        repo_base=$(echo ${repo_ent} | sed 's/-enterprise.*tar.gz$//')
        repo_os=$(ls mender-${RELEASE_VERSION}-src/${repo_base}* | grep -v ${repo_ent})
        echo "Deleting file ${repo_os}"
        rm ${repo_os}
    done
fi

echo
read -p "Print LICENSE files? " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    for repo in $(ls mender-${RELEASE_VERSION}-src); do
        license_file=$(tar -atf mender-${RELEASE_VERSION}-src/${repo} | grep LICENSE | head -n1)
        echo
        echo "==== Head of ${license_file} ===="
        echo
        tar -axf mender-${RELEASE_VERSION}-src/${repo} ${license_file} -O | head
    done
fi

tar -cf mender-${RELEASE_VERSION}-src.tar mender-${RELEASE_VERSION}-src
echo
echo
echo "Done \o/"
echo "Generated file mender-${RELEASE_VERSION}-src.tar with contents:"
tar tf mender-${RELEASE_VERSION}-src.tar
