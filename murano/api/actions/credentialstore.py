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
from oslo.config import cfg
from murano.api.actions.configFileCredentialsStore import ConfigFileCredentialStore
from murano.openstack.common.gettextutils import _  # noqa

cred_opts = [
 cfg.StrOpt('credentialStore',
  default='fileStorage',
  help=_('Specify a credentials store type.')),
 ]
cfg.CONF.register_opts(cred_opts)


class CredentialStoreFactory:
    def getStore(self):
        type = cfg.CONF.credentialStore
        if type == 'fileStorage':
            return ConfigFileCredentialStore()
