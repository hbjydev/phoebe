---
icon: octicons/shield-check-24
---

# Cert-Manager

[Cert-Manager](https://cert-manager.io) is a Kubernetes operator to manage TLS
certificates within a cluster, with providers for private CAs, as well as other
generation methods like using Let's Encrypt/ACME services to get public TLS
certs.

I use it within my cluster to generate a wildcard certificate for `*.hayden.moe`
so that I have HTTPS on all my HTTP services exposed by [Envoy](../infrastructure/envoy.md).

It handles rotating the certificate prior to expiry for me, so that in effect I
never have to think about keeping on top of certificates, they're just...
handled.

I also have [External Secrets](./external-secrets.md) configured to push the
current certificate to 1Password so that things like my Unifi controller can use
it too.
