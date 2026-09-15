{{ if and .Node.RuntimeData.TalosVersion (semverCompare "< 1.14.0-0" .Node.RuntimeData.TalosVersion) -}}
cluster:
  allowSchedulingOnControlPlanes: true
{{ else -}}
apiVersion: v1alpha1
kind: KubeNodeConfig
taints:
  node-role.kubernetes.io/control-plane:
    $patch: delete
{{ end -}}
