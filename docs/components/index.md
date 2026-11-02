# Components

This section documents the hardware, infrastructure, tools, and services that
make up Phoebe and its dependencies.

Start with [Hardware](./hardware.md) for the machines and network.

## Infrastructure

- [Talos](./infrastructure/talos.md): The operating system and node management.
- [Cilium](./infrastructure/cilium.md): Cluster networking and load balancing.
- [Envoy Gateway](./infrastructure/envoy.md): Routes traffic to services.
- [Multus](./infrastructure/multus.md): Adds network interfaces to workloads.

## Tools

- [cert-manager](./tools/cert-manager.md): Issues certificates for HTTPS.
- [External DNS](./tools/external-dns.md): Documentation placeholder.
- [External Secrets](./tools/external-secrets.md): Documentation placeholder.
- [Volsync](./tools/volsync.md): Documentation placeholder. See [Backups](../flows/backups.md) for the workflow.

## Services

- [Cloudflare](./services/cloudflare/index.md): DNS and external access.
- [UpCloud](./services/upcloud/index.md): Cloud services and object storage.
- [Media](./services/media/index.md): Media servers and download clients.
- [Keycloak](./services/keycloak.md): Identity and single sign-on.
- [Gatus](./services/gatus.md): Documentation placeholder.
