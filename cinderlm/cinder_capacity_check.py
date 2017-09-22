#!/usr/bin/env python
#
# (c) Copyright 2016 Hewlett Packard Enterprise Development LP
# (c) Copyright 2017 SUSE LLC
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

from __future__ import print_function

from cinderclient.client import Client as CinderClient
import ConfigParser
import socket
import sys
import time
import traceback

cinderlm_conf_file = "/etc/cinderlm/cinderlm.conf"

# This name is known by monasca - do NOT change
MODULE_SERVICE_NAME = 'block-storage'

capacity_metrics = {'cinderlm.cinder.backend.total.size':
                    'Total Capacity Metric',
                    'cinderlm.cinder.backend.total.avail':
                    'Total Available Capacity Metric',
                    'cinderlm.cinder.backend.physical.list':
                    'Cinder physical backend list'}


def metric(name, value, dimensions, timestamp, msg=None):
    """Construct the metric dictionary

       To list these metrics (for say the last two hours):
       monasca measurement-list cinderlm.cinder.backend.total.size -120  \
         --dimensions hostname=<hostname>,backendname=<backend name>, \
         name=<unique pool name>
       monasca measurement-list cinderlm.cinder.backend.total.avail -120  \
         --dimensions hostname=<hostname>,backendname=<backend name>, \
         name=<unique pool name>
       monasca measurement-list cinderlm.cinder.backend.physical.list -120 \
         --dimensions hostname=<hostname>,backends=physical
    """
    metric = {
        'metric': name,
        'value': value,
        'dimensions': dimensions,
        'timestamp': timestamp,
    }
    if msg is None:
        msg = capacity_metrics.get(name, 'Unknown Metric')
    metric['value_meta'] = {'msg': msg}

    return metric


def get_cinder_client():

    cp = ConfigParser.RawConfigParser()
    cp.read(cinderlm_conf_file)
    cinderlm_username = cp.get('DEFAULT', 'cinderlm_user')
    cinderlm_password = cp.get('DEFAULT', 'cinderlm_password')
    cinderlm_project_name = cp.get('DEFAULT', 'cinderlm_project_name')
    cinderlm_ca_cert_file = cp.get('DEFAULT', 'cinderlm_ca_cert_file')
    keystone_auth_url = cp.get('DEFAULT', 'cinderlm_auth_url')
    cinder_client_version = 2

    return CinderClient(cinder_client_version,
                        username=cinderlm_username,
                        api_key=cinderlm_password,
                        project_id=cinderlm_project_name,
                        auth_url=keystone_auth_url,
                        endpoint_type='internalURL',
                        cacert=cinderlm_ca_cert_file)


def _get_capacity():
    cinder_client = get_cinder_client()
    return cinder_client.pools.list(detailed=True)


def get_capacity():
    results = []
    backend_capacity_info = []
    physical_backend_list = []
    cp = ConfigParser.RawConfigParser()
    cp.read(cinderlm_conf_file)
    run_capacity_check = cp.get('DEFAULT', 'cinderlm_capacity_check')
    if run_capacity_check == "True":
        try:
            backend_capacity_info = _get_capacity()
        except Exception:
            t, v, tb = sys.exc_info()
            backtrace = ' '.join(traceback.format_exception(t, v, tb))
            # Because the length of the value_meta string is limited only take
            # the last 1900 characters, hard limit is 2048.
            backtrace = backtrace.replace('\n', ' ')[-1900:]
            # We were expecting size and avail metrics
            size_data = dict(metric='cinderlm.cinder.backend.total.size',
                             value=-1,
                             dimensions={'service': MODULE_SERVICE_NAME,
                                         'hostname': socket.gethostname(),
                                         'component': 'cinder-capacity',
                                         'name': 'undetermined',
                                         'backendname': 'undetermined'},
                             value_meta={'get_capacity': backtrace})
            avail_data = dict(metric='cinderlm.cinder.backend.total.avail',
                              value=-1,
                              dimensions={'service': MODULE_SERVICE_NAME,
                                          'hostname': socket.gethostname(),
                                          'component': 'cinder-capacity',
                                          'name': 'undetermined',
                                          'backendname': 'undetermined'},
                              value_meta={'get_capacity': backtrace})
            physical_backend_data = dict(
                metric='cinderlm.cinder.backend.physical.list',
                value=-1,
                dimensions={'service': MODULE_SERVICE_NAME,
                            'hostname': socket.gethostname(),
                            'component': 'cinder-backends',
                            'backends': 'undetermined'},
                value_meta={'get_backends': backtrace})
            results.extend([size_data, avail_data, physical_backend_data])

        for backend in backend_capacity_info:
            try:
                backend.total_capacity_gb = float(backend.total_capacity_gb)
            except ValueError:
                backend.total_capacity_gb = float("-1")
            total_size = metric('cinderlm.cinder.backend.total.size',
                                backend.total_capacity_gb,
                                {'service': MODULE_SERVICE_NAME,
                                 'hostname': socket.gethostname(),
                                 'component': 'cinder-capacity',
                                 'name': backend.name,
                                 'backendname': backend.volume_backend_name},
                                time.time())
            results.append(total_size)
            try:
                backend.free_capacity_gb = float(backend.free_capacity_gb)
            except ValueError:
                backend.free_capacity_gb = float("-1")
            total_avail = metric('cinderlm.cinder.backend.total.avail',
                                 backend.free_capacity_gb,
                                 {'service': MODULE_SERVICE_NAME,
                                  'hostname': socket.gethostname(),
                                  'component': 'cinder-capacity',
                                  'name': backend.name,
                                  'backendname': backend.volume_backend_name},
                                 time.time())
            results.append(total_avail)
            # Generate the list of backends
            physical_backend_list.append(backend.name)

        physical_backend_string = ",".join(physical_backend_list)
        physical_backends = metric('cinderlm.cinder.backend.physical.list',
                                   len(physical_backend_list),
                                   {'service': MODULE_SERVICE_NAME,
                                    'hostname': socket.gethostname(),
                                    'component': 'cinder-backends',
                                    'backends': 'physical'},
                                   time.time(), physical_backend_string)
        results.append(physical_backends)

    return results
