<div align="center">

<img src="https://avatars.githubusercontent.com/in/1354746?s=512" alt="A picture of Phoebe, one of the moons of Saturn" align="center" width="175px" height="175px" />

### <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f680/512.gif" alt="🚀" width="16" height="16"> Phoebe GitOps <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f6a7/512.gif" alt="🚧" width="16" height="16">

_The cluster that runs on my desk, a bare metal Talos Kubernetes cluster, provisioned using `talosctl`, `helm`, and `flux`._

</div>

<div align="center">

[![Status-Page](https://img.shields.io/uptimerobot/status/m793599155-ba1b18e51c9f8653acd0f5c1?color=brightgreeen&label=Status%20Page&style=for-the-badge&logo=statuspage&logoColor=white)](https://status.hayden.moe)&nbsp;&nbsp;
[![Alertmanager](https://img.shields.io/uptimerobot/status/m793494864-dfc695db066960233ac70f45?color=brightgreeen&label=Alertmanager&style=for-the-badge&logo=prometheus&logoColor=white)](https://status.hayden.moe)

</div>

---

## Overview

This is a monorepo for the cluster that lives on my desk, which I called
`phoebe`. It uses [Flux](https://fluxcd.io) to deploy services from this
repository into my cluster, and a combination of [SOPS](https://getsops.io/) and
[1Password](https://1password.com) to inject secrets into those services.

It automatically updates itself over time using
[Renovate](https://docs.renovatebot.com/), and tests pull requests for those
updates using [GitHub Actions](https://github.com/features/actions).

---

## Kubernetes

My Kubernetes cluster is deployed with [Talos](https://www.talos.dev). This
repository's structure is largely based on the amazing work put in over at
[`onedr0p/home-ops`](https://github.com/onedr0p/home-ops), but running my own
services and configurations.

### Core Components

- [cert-manager](https://github.com/cert-manager/cert-manager): Manages TLS certificates via Let's Encrypt.
- [cilium](https://github.com/cilium/cilium): eBPF-based networking and L2 load balancing with VIPs.
- [external-dns](https://github.com/kubernetes-sigs/external-dns): Pushes DNS updates to CloudFlare and my internal DNS server when changes are needed.
- [external-secrets](https://github.com/external-secrets/external-secrets): Managed Kubernetes secrets using [1Password Connect](https://github.com/1Password/connect).
- [longhorn](https://github.com/longhorn/longhorn): Clustered storage system that handles all the difficult things for me, and is very easy to deploy.
- [sops](https://github.com/getsops/sops): Managed secrets for Kubernetes, encrypted with Age, safely committed to Git.

---

## Acknowledgements

Thanks to all the people who donate their time to the
[Home Operations](https://discord.gg/home-operations) Discord community. Their
help, especially that of [onedr0p](https://github.com/onedr0p), has been
invaluable in getting my setup working to the degree it does.

They host a mirror of Helm charts I make use of too. They mirror charts with no
OCI registry available to `ghcr.io`, allowing me to keep all of my Helm charts
available over OCI images.
