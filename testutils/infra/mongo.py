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

from pymongo import MongoClient as PyMongoClient
from pymongo import errors

from testutils.infra.container_manager.kubernetes_manager import isK8S
from datetime import datetime

TENANT_LOCK_TIMEOUT_SEC = 300


class MongoClient:
    def __init__(self, addr="mender-mongo:27017"):
        self.client = PyMongoClient(addr)

    def setup_tenant_locking(self):
        db = self.client.tenantadm
        tests = db.tests
        tests.create_index([("tenant_id", 1)], unique=True)
        tests.create_index([("lock_ts", 1)], expireAfterSeconds=TENANT_LOCK_TIMEOUT_SEC)

    def cleanup(self):
        if isK8S():
            return
        dbs = self.client.list_database_names()
        dbs = [d for d in dbs if d not in ["local", "admin", "config", "workflows"]]
        for d in dbs:
            self.client.drop_database(d)

    def lock_tenant(self, tenant_id: str) -> bool:
        db = self.client.tenantadm
        tests = db.tests
        tenant = {"tenant_id": tenant_id, "lock_ts": datetime.utcnow()}
        try:
            tests.insert_one(tenant)
        except errors.DuplicateKeyError:
            return False
        return True
