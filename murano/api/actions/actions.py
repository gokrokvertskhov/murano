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

from webob import exc

from oslo.config import cfg

from murano.common import policy
from murano.common import wsgi
from murano.db import models
from murano.db.services import environments as envs
from murano.db.services import sessions
from murano.db import session as db_session

from murano.openstack.common.gettextutils import _  # noqa
from murano.openstack.common import log as logging
from murano.services import actions

from murano.api.actions.credentialstore import CredentialStoreFactory
from keystoneclient.v2_0 import client


LOG = logging.getLogger(__name__)


class Controller(object):
    def execute(self, request, environment_id, action_id, body):

        LOG.debug('Action:Execute <ActionId: {0}>'.format(action_id))

        unit = db_session.get_session()
        environment = unit.query(models.Environment).get(environment_id)

        if environment is None:
            LOG.info(_('Environment <EnvId {0}> '
                       'is not found').format(environment_id))
            raise exc.HTTPNotFound

        target_tenant_id = environment.tenant_id
        # Now we need to authenticate ourselves
        cred_storage = CredentialStoreFactory().getStore()
        #TODO Implement tenant_id_to_project
        admin_kc = get_admin_keystoneclient()
        try:
            project_name = tenant_id_to_project(admin_kc, target_tenant_id)
        except:
            LOG.error('Actions: Can`t find tenant for this action.')
            raise exc.HTTPNotFound('No projects found for action '
                                   '{0}'.format(action_id))

        creds = cred_storage.getCredentials(project_name)

        if creds == None:
            LOG.error('Action: Execution of <ActionId: {0}> failed. '
                      'No valid credentials available.'.format(action_id))
            raise exc.HTTPForbidden()

        #Creds={'username:'', 'password''}
        # We need to add auth_url, endpoint, project_name
        auth_url = getAuthUrl()
        creds['auth_url'] = "http://172.16.40.137:5000/v2.0"
        creds['endpount'] = "http://172.16.40.137:5000/v2.0"
        creds['project_name'] = project_name

        #Obtain token for user authenticated in proper tenant
        try:
            kc=client.Client(**creds)
            kc.authenticate()
        except:
            LOG.error('Actions: Stored credentials are not valid for this '
                      'environment and action. '
                      '{0} {1} ({2}:{3})'.format(environment_id,
                                                 action_id,
                                                 environment.name,
                                                 action_id))


        # no new session can be opened if environment has deploying status
        env_status = envs.EnvironmentServices.get_status(environment_id)
        if env_status in (envs.EnvironmentStatus.DEPLOYING,
                          envs.EnvironmentStatus.DELETING):
            LOG.info(_('Could not open session for environment <EnvId: {0}>,'
                       'environment has deploying '
                       'status.').format(environment_id))
            raise exc.HTTPForbidden()


        user_id = kc.user_id
        session = sessions.SessionServices.create(environment_id, user_id)

        if not sessions.SessionServices.validate(session):
            LOG.error(_('Session <SessionId {0}> '
                        'is invalid').format(session.id))
            raise exc.HTTPForbidden()

        actions.ActionServices.execute(action_id, session, unit,
                                       kc.auth_token, body or {})


def create_resource():
    return wsgi.Resource(Controller())

def getAuthUrl():
    auth_url = None
    try:
        auth_url = cfg.CONF.keystone_authtoken.auth_url
    except:
        pass
    finally:
        if auth_url == None:
            auth_url='{0}://{1}:{2}/v2.0/'.format(
                cfg.CONF.keystone_authtoken.auth_protocol,
                cfg.CONF.keystone_authtoken.auth_host,
                cfg.CONF.keystone_authtoken.auth_port
            )
        return auth_url

def tenant_id_to_project(kc, tenant_id):
    tenant = kc.tenants.get(tenant_id)
    return tenant.name

def get_admin_keystoneclient():
    admin_creds = {
        'username': cfg.CONF.keystone_authtoken.admin_user,
        'password': cfg.CONF.keystone_authtoken.admin_password,
        'auth_url': getAuthUrl(),
        'endpoint': getAuthUrl(),
        'project_name': cfg.CONF.keystone_authtoken.admin_tenant_name}
    kc = client.Client(**admin_creds)
    kc.authenticate()
    return kc
