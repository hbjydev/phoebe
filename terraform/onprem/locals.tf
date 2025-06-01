locals {
  node_names = [
    "hy-net-vm-01",
  ]

  images = {
  }

  vm = {}

  k8s = {
    "phoebe" = {
      node_names = ["hy-net-vm-01"]
    }
  }
}
