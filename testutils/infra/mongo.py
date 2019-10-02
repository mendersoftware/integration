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

from pymongo import MongoClient

class MongoClient:
    def __init__(self, addr):
        self.client = MongoClient('mender-mongo:27017')

    def cleanup(self, db):
        dbs = self.client.database_names()
        dbs = [d for d in dbs if d not in ['local', 'admin']]
        for d in dbs:
            self.client.drop_database(d)
