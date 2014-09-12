#    Copyright (c) 2014 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import json
from oslo.config import cfg
from murano.openstack.common.gettextutils import _  # noqa


file_opts = [
 cfg.StrOpt('credentialsFile',
  default='etc/murano/credentials.json',
  help=_('Full path file name where credentials are stored.')),
 ]

cfg.CONF.register_opts(file_opts, 'credentials_fileStorage')


class ConfigFileCredentialStore:
    file_name = cfg.CONF.credentials_fileStorage.credentialsFile
    def __init__(self):
        self.storage = None
        self.reloadFile()

    def reloadFile(self):
        with open(self.file_name, 'r') as f:
            self.storage = json.load(f)

    def getCredentials(self, tenant):
        return self.storage[tenant]
