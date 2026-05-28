from netaddr import IPSet, IPNetwork

reserved=["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]
world=IPSet(IPNetwork("0.0.0.0/0"))
excluded=IPSet([IPNetwork(n) for n in reserved])

[print(f"   - {n}") for n in (world ^ excluded).iter_cidrs()]
