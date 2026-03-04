---
icon: simple/cloudflare
---

# Cloudflare

[Cloudflare](https://cloudflare.com) is a web infrastructure and security company
that provides DNS, CDN, DDoS protection, and various other services.

I use Cloudflare for DNS management and secure external access to my homelab
services without exposing any ports on my router.

<div class="grid cards" markdown>

-   :octicons-shield-lock-24:{ .lg .middle } **Cloudflare Tunnels**

    ---

    Cloudflare Tunnels provide secure, outbound-only connections from my cluster
    to Cloudflare's edge network, eliminating the need for port forwarding and
    exposing my home IP address.

    This works by running `cloudflared` as a daemon in the cluster that
    establishes an encrypted tunnel to Cloudflare. External traffic is routed
    through this tunnel to reach services behind [Envoy Gateway](../../infrastructure/envoy.md).

    [:octicons-arrow-right-24: Learn More](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)

-   :octicons-globe-24:{ .lg .middle } **DNS Management**

    ---

    I manage all my DNS records through Cloudflare, which integrates with
    [external-dns](../../tools/external-dns.md) to automatically create and
    update DNS records when services are deployed to the cluster.

</div>
