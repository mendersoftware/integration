# Copyright 2024 Northern.tech AS
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

# A simple script for praparing command line arguments for splitting
# pytest classes into a Gitlab Parallel matrix.

import os
import re
import subprocess
import sys

INDEX = int(os.environ.get("CI_NODE_INDEX", "1"))
TOTAL = int(os.environ.get("CI_NODE_TOTAL", "1"))

output = subprocess.check_output(["pytest", "--co", "tests"] + sys.argv[1:])

classes = []
expr = re.compile("<Class ([^>]+)>")
for line in output.decode("UTF-8").splitlines():
    match = expr.search(line)
    if match:
        classes.append(match.group(1))
classes.sort()


n_batch = len(classes) // TOTAL
n_rest = len(classes) % TOTAL

offset = n_batch * (INDEX - 1)
if INDEX <= n_rest:
    n_batch += 1
    offset += INDEX
else:
    offset += n_rest

print(" or ".join(classes[offset : offset + n_batch]))
