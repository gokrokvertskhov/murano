#    Copyright (c) 2013 Mirantis, Inc.
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
import base64
import json
import pickle
import six
import uuid

from oslo.config import cfg
from murano import context
from murano.api.cloudfoundry import auth as keystone_auth
from murano.db.catalog import api as db_api
from murano.openstack.common import log as logging
from murano.openstack.common import wsgi

import muranoclient.client as client

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

class CFMuranoMapper(object):
    def __init__(self):
        self.spaceToEnv = {}
        self.orgToTenant = {}
        self.srv_instances = {}

    def getEnvironment(self, space_guid):
        return self.spaceToEnv.get(space_guid, None)

    def getTenant(self, org_guid):
        return self.orgToTenant.get(org_guid, None)

    def setEnvironment(self, space_guid, env_id):
        self.spaceToEnv[space_guid] = env_id

    def setTenant(self, org_guid, tenant_id):
        self.orgToTenant[org_guid] = tenant_id

    def mapInstanceToService(self, instance_id, service_id, env_id, tenant):
        self.srv_instances[instance_id] = {'service_id': service_id,
                                           'env_id': env_id,
                                           'tenant': tenant}

    def getServiceForInstance(self, instance_id):
        return self.srv_instances.get(instance_id, None)

MAPPER = CFMuranoMapper()

class Controller(object):
    """
        WSGI controller for application catalog resource in Murano v1 API
    """
    def list(self, req):
        user, passwd, keystone = self.check_auth(req)
        #Once we get here we were authorized by keystone
        token = keystone.auth_ref['token']['id']

        ctx = context.RequestContext(user=user, tenant='', is_admin=True)

        packages = db_api.package_search({},ctx)
        services = []
        for package in packages:
            services.append(self.package_to_service(package))

        resp = {'services': services}


        return resp

    def create_env(self, m_cli, space_guid):
        LOG.debug('Adding new environment for the space: %s' % space_guid)
        body = {'name': space_guid}
        env_id = m_cli.environments.create(body)
        MAPPER.setEnvironment(space_guid, env_id)
        return env_id

    def provision(self, req, body, instance_id):

        # Parse body parameter
        #{
        #"service_id":        "service-guid-here",
        #"plan_id":           "plan-guid-here",
        #"organization_guid": "org-guid-here",
        #"space_guid":        "space-guid-here"
        #}

        data = json.loads(req.body)
        space_guid = data['space_guid']
        org_guid = data['organization_guid']
        plan_id = data['plan_id']
        service_id = data['service_id']

        # We will map space_guid to Murano Env
        (tenant, env_id) = self.getOSInfo(space_guid, org_guid)
        LOG.debug('Provisioning in tenant: %s env: %s' % (tenant, env_id))

        # Now as we have all parameters we can try to auth user in actual tenant

        user, passwd, keystone = self.check_auth(req, tenant)
        #Once we get here we were authorized by keystone
        token = keystone.auth_ref['token']['id']
        m_cli = muranoclient(token)

        if env_id is None:
            env_id = self.create_env(m_cli, space_guid)
        LOG.debug('Auth: %s' % keystone.auth_ref)
        tenant_id = keystone.auth_ref['token']['id']
        ctx = context.RequestContext(user=user, tenant=tenant_id, is_admin=True)

        package = db_api.package_get(service_id, ctx)
        LOG.debug('Adding service %s' % package.name)

        service = self.makeService(space_guid, package)
        MAPPER.mapInstanceToService(instance_id, service['?']['id'], env_id.id, tenant)
        service.update(self.makeInstance())

        # Now we need to obtain session to modify the env
        session_id = create_session(m_cli, env_id.id)
        m_cli.services.post(env_id.id,
                      path='/',
                      data=service,
                      session_id=session_id)
        m_cli.sessions.deploy(env_id.id, session_id)
        return {}

    def bind(self, req, instance_id, id):
        service = MAPPER.getServiceForInstance(instance_id)
        if not service:
            return {}

        service_id = service['service_id']
        env_id = service['env_id']
        tenant = service['tenant']
        user, passwd, keystone = self.check_auth(req, tenant)
        # Once we get here we were authorized by keystone
        token = keystone.auth_ref['token']['id']
        m_cli = muranoclient(token)

        env = env_get(m_cli, env_id)
        LOG.debug ('Got environemtn %s' % env)
        return

    def unbind(self, req, instance_id, id):
        return

    def deprovision(self, req, instance_id):
        service = MAPPER.getServiceForInstance(instance_id)
        if not service:
            return {}

        service_id = service['service_id']
        env_id = service['env_id']
        tenant = service['tenant']
        user, passwd, keystone = self.check_auth(req, tenant)
        #Once we get here we were authorized by keystone
        token = keystone.auth_ref['token']['id']
        m_cli = muranoclient(token)

        session_id = create_session(m_cli, env_id)

        m_cli.services.delete(env_id,'/' + service_id, session_id)
        m_cli.sessions.deploy(env_id, session_id)

        return {}

    #Murano and OS specific calls

    def list_env(self, req):
        return MAPPER.spaceToEnv

    def list_tenants(self, req):
        return MAPPER.orgToTenant

    def add_tenant(self, req, body):
        data = json.loads(req.body)
        LOG.debug('Add mapping: %s' % data)
        for org, tenant in six.iteritems(data):
            MAPPER.setTenant(org, tenant)
        return

    def dump_db(self, req):
        global MAPPER
        with open('data.pkl', 'wb') as f:
            pickle.dump(MAPPER, f)
        return

    def load_db(self, req):
        global MAPPER
        with open('data.pkl', 'r') as f:
            MAPPER = pickle.load(f)
        return


    def check_auth(self, req, tenant=None):
        auth = req.headers.get('Authorization', None)
        if auth is None:
            raise Exception('Authentication needed.')

        auth_info = auth.split(' ')[1]
        auth_decoded = base64.b64decode(auth_info)
        user = auth_decoded.split(':')[0]
        password = auth_decoded.split(':')[1]
        if tenant:
            keystone = keystone_auth.authenticate(user, password, tenant)
        else:
            keystone = keystone_auth.authenticate(user, password)
        return (user, password, keystone)

    def package_to_service(self, package):
        srv = {}
        srv['id'] = package.id
        srv['name'] = package.name
        srv['description'] = package.description
        srv['bindable'] = True
        srv['tags'] = []
        for tag in package.tags:
            srv['tags'].append(tag.name)
        plan = {'id': package.id+'-1',
                'name': 'default',
                'description': 'Default plan for the service %s' % package.name}
        srv['plans'] = [plan]
        return srv

    def getOSInfo(self, space_guid, org_guid):
        env_id = MAPPER.getEnvironment(space_guid)
        tenant_id = MAPPER.getTenant(org_guid)

        return (tenant_id, env_id)

    def makeInstance(self):
        id = str(uuid.uuid4())
        return dict(instance={"flavor": "m1.medium", "image": "F18-x86_64-cfntools",
                              "?": {"type": "io.murano.resources.LinuxMuranoInstance",
                                    "id": id},
                              "name": "wvbtehwlbl08z2"})

    def makeService(self, name, package):
        id = str(uuid.uuid4())

        return {"name": name,
                "?": {"_26411a1861294160833743e45d0eaad9": {"name": package.name},
                              "type": package.fully_qualified_name
                    , "id": id}}


def muranoclient(token_id):
    endpoint = "http://localhost:8082"
    insecure = False


    LOG.debug('Murano::Client <Url: {0}, '
              'TokenId: {1}>'.format(endpoint, token_id))

    return client.Client(1, endpoint=endpoint, token=token_id,
                         insecure=insecure)


def create_session(client, environment_id):
    id = client.sessions.configure(environment_id).id
    return id

def create_resource():
    return wsgi.Resource(Controller())

def env_get(client, env_id):
    session_id = create_session(client, env_id)
    env = client.environments.get(env_id, session_id)
    return env