# Copyright 2018 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
import subprocess
import socket

PROJECT_NAME='backendtests'

def exec(container_id, cmd):
    cmd = ['docker', 'exec', '{}'.format(container_id)] + cmd
    ret = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return ret.stdout.decode('utf-8').strip()

def getid(service_name):
    cmd = ['docker', 'ps', '-q', '-f', 'name=backendtests_{}_1'.format(service_name)]
    ret = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    tid = ret.stdout.decode('utf-8').strip()
    if tid == '':
        raise RuntimeError('container id for {} not found'.format(service_name))

    return ret.stdout.decode('utf-8').strip()
