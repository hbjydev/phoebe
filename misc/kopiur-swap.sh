#!/usr/bin/env bash
set -euo pipefail

app="${1}"
namespace="${2}"

snap_name="${app}-${namespace}-kopiur-move-$(date +%Y%m%d%H%M%S)"

pods=$(kubectl get pods -n "${namespace}" -l "app=${app}" -o jsonpath='{.items[*].metadata.name}')
replicas=$(kubectl get deployment "${app}" -n "${namespace}" -o jsonpath='{.spec.replicas}')

kubectl scale --replicas=0 "deployment/${app}" -n "${namespace}"
for pod in ${pods}; do
  kubectl wait --for=delete pod/"${pod}" -n "${namespace}" --timeout=60s
done

kubectl kopiur snapshot now \
  --policy "${app}" \
  --name "${snap_name}" \
  --namespace "${namespace}" \
  --wait \
  --logs

kubectl delete pvc -n "${namespace}" -l "app.kubernetes.io/name=${app}"

just kube sync-ks

kubectl wait --for=jsonpath='{.status.phase}'=Bound pvc -n "${namespace}" -l "app.kubernetes.io/name=${app}" --timeout=60s
kubectl scale --replicas="${replicas}" "deployment/${app}" -n "${namespace}"
