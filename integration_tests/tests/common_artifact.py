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

import subprocess
import tempfile

from ..MenderAPI import logger


def get_script_artifact(
    script, artifact_name, device_type, output_path, extra_args=None
):
    with tempfile.NamedTemporaryFile(suffix="testdeployment") as tf:
        tf.write(script)
        tf.seek(0)
        out = tf.read()
        logger.info(f"Script: {out}")
        script_path = tf.name

        cmd = f"mender-artifact write module-image -T script -n {artifact_name} -t {device_type} -o {output_path} -f {script_path}"
        if extra_args is not None:
            cmd += f" {extra_args}"

        logger.info(f"Executing command: {cmd}")
        subprocess.check_call(cmd, shell=True)

        return output_path
