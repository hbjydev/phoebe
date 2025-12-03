---
icon: simple/cilium
---

# Cilium

[Cilium](https://cilium.io) is a
[CNI (Container Network Interface)](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/network-plugins/)
for Kubernetes that provides networking between all of the services I run in the
cluster.

It _also_ provides useful features like Load Balancing without needing dedicated
hardware, which is useful in a lower-budget lab like this one.

## Features

Let's run through the features of Cilium I use in a little more depth.

### :octicons-plug-16: Container Networking

TODO

### :octicons-broadcast-16: Load Balancing

The cluster uses Cilium as a Load Balancer using
[BGP](https://www.cloudflare.com/en-gb/learning/security/glossary/what-is-bgp/).

The way this works is by advertising routes with BGP to my router, which is
configured as a BGP peer. These routes are stored by my router and then
rebroadcasted to the rest of my network, making the services with
`type: LoadBalancer` in my cluster (like [Envoy](./envoy)) available to all the
clients connected to my Wi-Fi and over Ethernet.

This allows me to have two gateways, an internal and external one, which route
traffic through my cluster, without having to buy dedicated load balancing
hardware or be working in a cloud environment, or figure out a hacky way to
route traffic to individual Kubernetes nodes (or, heaven fobid, the pods
themselves).
