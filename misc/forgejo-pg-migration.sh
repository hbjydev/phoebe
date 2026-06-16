#!/usr/bin/env bash
set -euxo pipefail

app_name="forgejo"
app_namespace="dev"
cluster_name="postgres"
cluster_namespace="database"

mkdir -p "$HOME/tmp"
workdir="$(mktemp -d -p "$HOME/tmp")"

kubectl port-forward --address 0.0.0.0 --namespace "${cluster_namespace}" "pod/${cluster_name}-1" 5432:5432 > /dev/null 2>&1 &
cluster_pid=$!

trap '{
  kill $cluster_pid
  # rm -rf "${workdir}"
}' EXIT

# Find current app pod
pod_name=$(kubectl get pods -n "${app_namespace}" -l app.kubernetes.io/name="${app_name}" -o jsonpath="{.items[0].metadata.name}")
push_uri=$(kubectl get secret -n "${app_namespace}" "${app_name}-postgres" -o json \
  | jq -r .data.url \
  | base64 -d \
  | sed "s/forgejo@/forgejo:forgejo@/" \
  | sed "s/pooler-rw.${cluster_namespace}.svc/localhost/" \
  | sed "s/5432\/${app_name}\?.*/5432\/${app_name}/" \
  | sed "s|/var/run/secrets/|/tmp/|")
echo "Detected Push URL: ${push_uri}"

# Fetch client & CA certs
mkdir -p "${workdir}/postgresql"
pg_cert=$(kubectl get secret -n "${app_namespace}" "postgres-client-ca" -o json)
echo "$pg_cert" | jq -r '.["tls.crt"]' | base64 -d > "${workdir}/postgresql/tls.crt"
echo "$pg_cert" | jq -r '.["tls.key"]' | base64 -d > "${workdir}/postgresql/tls.key"

# Grab data dump
kubectl cp "${app_namespace}/${pod_name}:/data/gitea/forgejo.db" "${workdir}/forgejo.db"

# Make DB schema backup
kubectl exec -n "${cluster_namespace}" "${cluster_name}-1" -c postgres -- pg_dump -d "${app_name}" -s > $workdir/schema.sql

# Scale down app deployment
kubectl scale deploy "${app_name}" --namespace="${app_namespace}" --replicas=0

# Recreate public schema
kubectl cnpg psql -n "${cluster_namespace}" "${cluster_name}" -- ${app_name} << EOF
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
ALTER SCHEMA public OWNER TO ${app_name};
EOF

# Reload schema
cat $workdir/schema.sql | kubectl cnpg psql -n "${cluster_namespace}" "${cluster_name}" -- ${app_name}

# Push new data into PostgreSQL
docker run \
  --rm \
  -v "${workdir}/forgejo.db:/forgejo.db:ro" \
  --network=host \
  --memory=4g \
  --shm-size=1g \
  --oom-kill-disable=false \
  ghcr.io/roxedus/pgloader \
    --with "prefetch rows = 500" \
    --with "batch concurrency = 1" \
    --with "quote identifiers" \
    --with "data only" \
    sqlite:///forgejo.db \
    "${push_uri}"

# Scale back up app deployment
kubectl scale deploy "${app_name}" --namespace="${app_namespace}" --replicas=1
