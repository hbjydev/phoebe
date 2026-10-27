<div align="center">

<img src="https://avatars.githubusercontent.com/in/1354746?s=512" alt="A picture of Phoebe, one of the moons of Saturn" align="center" width="175px" height="175px" />

### <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f680/512.gif" alt="🚀" width="16" height="16"> Phoebe GitOps <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f6a7/512.gif" alt="🚧" width="16" height="16">

_The cluster that runs on my desk: a bare metal Talos Kubernetes cluster, managed with Flux._

</div>

<div align="center">

[Status page](https://status.hayden.moe)

</div>

---

## Overview

This is a monorepo for the cluster that lives on my desk, which I called
`phoebe`. It uses [Flux](https://fluxcd.io) to deploy services from this
repository into my cluster, and a combination of [SOPS](https://getsops.io/) and
[1Password](https://1password.com) to inject secrets into those services.

Dependency updates come from [Renovate](kubernetes/apps/dev/renovate), which
runs in the cluster and opens pull requests on my self-hosted
[Forgejo](kubernetes/apps/dev/forgejo) instance. Flux reconciles changes from
this repository into the cluster.

---

## Kubernetes

My Kubernetes cluster is deployed with [Talos](https://www.talos.dev). This
repository's structure is largely based on the amazing work put in over at
[`onedr0p/home-ops`](https://github.com/onedr0p/home-ops), but running my own
services and configurations. The current [Talos configuration](talos/topf.yaml)
defines a single control-plane node that also runs application workloads.

### Core Components

- [Flux Operator](kubernetes/apps/flux-system): Manages Flux and the GitOps reconciliation of cluster resources.
- [Cilium](kubernetes/apps/kube-system/cilium): eBPF-based networking, network policies, and load balancer IP advertisement over BGP to my UniFi router.
- [Envoy Gateway](kubernetes/apps/network/envoy-gateway): Internal and external application routing using the Kubernetes Gateway API.
- [Tailscale](kubernetes/apps/network/tailscale): Private access to cluster services and subnet routing.
- [cert-manager and trust-manager](kubernetes/apps/cert-manager): TLS certificate issuance and trust bundle distribution.
- External DNS: Separate deployments manage [Cloudflare](kubernetes/apps/network/cloudflare-dns) and [UniFi](kubernetes/apps/network/unifi-dns) DNS records.
- [External Secrets](kubernetes/apps/external-secrets): Syncs Kubernetes secrets from 1Password Connect.
- [SOPS](kubernetes/components/common/sops): Keeps Age-encrypted secrets in Git.
- [Miroir](kubernetes/apps/miroir-system): Persistent volumes backed by a local LVM thin pool. The default `miroir-local` storage class uses one replica.
- [Garage](kubernetes/apps/garage-system): S3-compatible object storage, managed by the Garage operator.
- [CloudNativePG](kubernetes/apps/cnpg-system) and [Dragonfly](kubernetes/apps/dragonfly-system): Operators for PostgreSQL databases and Redis-compatible data stores.
- [Kanidm](kubernetes/apps/security/kaniop): Identity and single sign-on, managed by Kaniop.
- [Observability](kubernetes/apps/observability): VictoriaMetrics, VictoriaLogs, and VictoriaTraces for telemetry; OpenTelemetry for collection; Grafana for dashboards; Alertmanager for alerts; and Gatus for status checks.

Media libraries are mounted separately over NFS from my NAS.

### Applications

Alongside the infrastructure, the cluster runs:

- [Media services](kubernetes/apps/media): Plex, Navidrome, Silo, and Seerr.
- [Home automation](kubernetes/apps/default): Home Assistant, with the *arr applications and [download clients](kubernetes/apps/downloads) in their own namespace.
- [Self-hosted services](kubernetes/apps/selfhosted): Immich, Paperless, Miniflux, SearXNG, and Tranquil.
- [Matrix](kubernetes/apps/matrix): Continuwuity and LiveKit.
- [AI services](kubernetes/apps/ai): Including LiteLLM, Hermes, and LLMKube.

The manifests under [`kubernetes/apps`](kubernetes/apps) are the source of truth
for the configured services.

---

## Acknowledgements

Thanks to all the people who donate their time to the
[Home Operations](https://discord.gg/home-operations) Discord community. Their
help, especially that of [onedr0p](https://github.com/onedr0p), has been
invaluable in getting my setup working to the degree it does.

They host a mirror of Helm charts I make use of too. They mirror charts with no
OCI registry available to `ghcr.io`, allowing me to keep all of my Helm charts
available over OCI images.
