#!/usr/bin/env netaddr

from netaddr import IPSet, IPNetwork
from json import dumps

subset = IPSet(IPNetwork("0.0.0.0/0"))
subset.remove("10.0.0.0/8")
subset.remove("172.16.0.0/12")
subset.remove("192.168.0.0/16")

for subnet in subset.iter_cidrs():
    print(dumps({'dst': str(subnet), 'gw': '192.168.20.1'}) + ',')
