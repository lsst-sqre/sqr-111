### Creating the Kubernetes environment

1. Create a kind cluster wtih `kind create cluster`
1. Start the cloud-ingress-provider with `pitchfork start --all`

### Installing Agentgateway

https://agentgateway.dev/docs/kubernetes/main/quickstart/install/

1. kubectl apply --server-side --force-conflicts -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.0/standard-install.yaml
1. helm upgrade -i agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds --create-namespace --namespace agentgateway-system --version 1.4.0-alpha.1 --set controller.image.pullPolicy=Always
1. helm upgrade -i agentgateway oci://cr.agentgateway.dev/charts/agentgateway --namespace agentgateway-system --version 1.4.0-alpha.1 --set controller.image.pullPolicy=Always \
  --wait
