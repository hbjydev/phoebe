---
icon: simple/envoyproxy
---

# Envoy Gateway

I use [Envoy Gateway](https://gateway.envoyproxy.io/) to provide ingress to my
cluster, with [Cilium](./cilium.md) providing the load balancing aspect.

The way I have it configured, Envoy consumes Kubernetes' [Gateway API](https://kubernetes.io/docs/concepts/services-networking/gateway/)
to set up routing to different services within the cluster, and uses TLS
certificates [cert-manager](../tools/cert-manager.md) generates to keep
everything encrypted on its way to the cluster.

For external access, I use [Cloudflare Tunnels](https://www.cloudflare.com/products/tunnel/)
instead of port forwarding, which provides secure, outbound-only connections to
the cluster without exposing any ports on my router.

```mermaid
flowchart TD
    wan(WAN)-->tunnel
    tunnel(Cloudflare Tunnel)-->envoy
    lbip(Load balancer IP)-->envoy
    envoy(Envoy)-- routes via -->httproute
    httproute(HTTPRoute resource)-- proxies traffic to -->svc
    svc(K8s service)-- routes traffic to -->pods
    pods(K8s pods)
```
