#!/usr/bin/env python
#
# (c) Copyright 2015,2016 Hewlett Packard Enterprise Development LP
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

import argparse
from cinder_capacity_check import get_capacity
import json
import os
import re
import socket
from swiftlm.hp_hardware import hpssacli
from swiftlm.utils.values import Severity
import sys
import time
import yaml


PROC_DIR = '/proc'

# This python module implements a single cinder service check to
# report the number of process of each cinder type running.
# In the longer term the process check should be broken out to
# constitute one of many newer tests and this file should remain
# the driver script for ALL diagnostics.

# This name is known by monasca - do NOT change
MODULE_SERVICE_NAME = 'block-storage'

# The name of metric to be reported
MODULE_METRIC_NAME = 'cinderlm.cinder.cinder_services'

# Cinder processes for which to perform a count
SUBSERVICES = [
    "cinder-volume",
    "cinder-backup",
    "cinder-api",
    "cinder-scheduler"
]


argparser = argparse.ArgumentParser(usage="Cinder Diagnostics Utility")


def create_arguments(parser):
    """Program arguments."""
    client_args = parser.add_argument_group('Cinder diagnostics arguments')
    client_args.add_argument('-j', '--json',
                             default=False, action='store_true',
                             help='Emit json if True, else emit yaml')
    client_args.add_argument('--cinder-services', dest='cinder_services',
                             default=False, action='store_true',
                             help='Do a process count of cinder services')
    client_args.add_argument('--cinder-capacity', dest='cinder_capacity',
                             default=False, action='store_true',
                             help='Do a check on cinder backend capacity')
    client_args.add_argument('--hpssacli', dest='hpssacli',
                             default=False, action='store_true',
                             help='Check local disk devices')


def metric(name, value, dimensions, timestamp):
    """Construct the metric dictionary

       To list these metrics (for say the last two hours):
       monasca measurement-list cinderlm.cinder.cinder_services -120  \
         --dimensions hostname=standard-ccp-c1-m1-mgmt,component=cinder-volume
    """
    metric = {
        'metric': name,
        'value': value,
        'dimensions': dimensions,
        'timestamp': timestamp,
    }

    if value > 0:
        msg = "%s is running" % dimensions['component']
    else:
        msg = "%s is not running" % dimensions['component']
    metric['value_meta'] = {'msg': msg}

    return metric


def _check_process(name):
    found = 0
    pid_re = re.compile("^\d+")
    for sub_directory in [d for d in os.listdir(PROC_DIR) if pid_re.match(d)]:
        if (os.path.exists(os.path.join(PROC_DIR, sub_directory, "cmdline"))):
            cmdline = os.path.join(PROC_DIR, sub_directory, "cmdline")
            try:
                if name in open(cmdline, "r").read():
                    found += 1
            except IOError:
                continue
    return found


def check_process(name):
    return _check_process(name)


def check_cinder_processes():
    results = []
    for subservice in SUBSERVICES:
        val = check_process(subservice)
        c = metric(MODULE_METRIC_NAME, val,
                   {'service': MODULE_SERVICE_NAME,
                    'hostname': socket.gethostname(),
                    'component': subservice},
                   time.time())
        results.append(c)

    return results


def check_hpssacli():
    """GET local smart array status

       Wrap swiftlm hpssacli diag to get results
    """
    # Needs root privileges to run
    results, slots = hpssacli.get_smart_array_info()
    if type(results) != list:
        # A single metric can be emitted in some cases:
        # <class 'swiftlm.utils.metricdata.MetricData'>
        # swiftlm.hp_hardware.hpssacli.smart_array failed with: \
        #     flock: failed to execute hpssacli: Permission denied
        results = [results]
    for slot in slots:
        results.extend(hpssacli.get_physical_drive_info(slot))
        results.extend(hpssacli.get_logical_drive_info(slot, cache_check=True))
    for result in results:
        # where possible change the service strings
        result.name = result.name.replace('swift', 'cinder')
        for key in result.dimensions.keys():
            if key == 'service':
                result.dimensions[key] = 'block-storage'
            result.dimensions[key] = result.dimensions[key].replace('swift',
                                                                    'cinder')
    # To print individual results do this...
    # for result in results:
    #     print(repr(result))
    return [result.metric() for result in results]


def main():
    create_arguments(argparser)
    args = argparser.parse_args()

    results = []
    if args.cinder_services:
        results = check_cinder_processes()
    if args.cinder_capacity:
        results.extend(get_capacity())
    if args.hpssacli:
        results.extend(check_hpssacli())
    if args.json:
        print(json.dumps(results, sort_keys=True, indent=4))
    else:
        yaml.add_representer(Severity, Severity.yaml_repr, yaml.SafeDumper)
        print(yaml.safe_dump(results,
                             allow_unicode=True,
                             default_flow_style=False))
    sys.exit(0)


if __name__ == '__main__':
    main()
