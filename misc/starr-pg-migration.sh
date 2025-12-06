#!/usr/bin/env bash
set -ex

app="${1:-}"
cluster_name="starr-pg"

if [[ "$app" == "" ]]; then
  echo "Usage: $0 <app-name>"
  exit 1
fi

mkdir -p "$HOME/tmp"
workdir="$(mktemp -d -p "$HOME/tmp")"

kubectl port-forward --address 0.0.0.0 "pod/${cluster_name}-1" 5432:5432 > /dev/null 2>&1 &
cluster_pid=$!

trap '{
  kill $cluster_pid
  rm -rf "${workdir}"
}' EXIT

# Find current app pod
pod_name=$(kubectl get pods -l app.kubernetes.io/name="${app}" -o jsonpath="{.items[0].metadata.name}")
push_uri=$(kubectl get secret "${cluster_name}-app" -o json | jq -r .data.uri | base64 -d | sed 's/starr-pg-rw.default/host.docker.internal/' | sed "s/app$/${app}/")

# Grab data dump
kubectl cp "default/${pod_name}:${app}.db" "${workdir}/app.db"

# Make DB schema backup
kubectl exec "${cluster_name}-1" -c postgres -- pg_dump -d "${app}" -s > $workdir/schema.sql

# Scale down app deployment
kubectl scale deploy "${app}" --replicas=0

# Recreate public schema
kubectl cnpg psql "${cluster_name}" -- ${app} << EOF
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
ALTER SCHEMA public OWNER TO app;
EOF

# Reload schema
cat $workdir/schema.sql | kubectl cnpg psql "${cluster_name}" -- ${app}

# Push new data into PostgreSQL
docker run \
  --rm \
  -v "${workdir}/app.db:/app.db:ro" \
  --network=host \
  ghcr.io/roxedus/pgloader \
    --with "quote identifiers" \
    --with "data only" \
    /app.db \
    "${push_uri}"

# Scale back up app deployment
kubectl scale deploy "${app}" --replicas=1
