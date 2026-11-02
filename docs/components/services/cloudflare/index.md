# Cloudflare

[Cloudflare](https://cloudflare.com) provides web infrastructure and security services.
I use Cloudflare for DNS management and secure external access to my homelab services.
My router does not need open inbound ports for this access.

## Cloudflare Tunnels

Cloudflare Tunnels connect my cluster to Cloudflare through outbound connections.
This avoids port forwarding and keeps my home IP address private.

The `cloudflared` daemon runs in the cluster and establishes an encrypted tunnel to Cloudflare.
External traffic passes through this tunnel to services behind [Envoy Gateway](../../infrastructure/envoy.md).

Read the [Cloudflare Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) for more details.

## DNS management

I manage my DNS records through Cloudflare.
[External DNS](../../tools/external-dns.md) creates and updates records when I deploy services to the cluster.
