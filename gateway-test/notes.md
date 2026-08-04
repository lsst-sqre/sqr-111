TLDR: I think https://agentgateway.dev does everything we want, including auth caching (and tons of stuff we don't need). I'm working on verifying that it actually does what we need. I'll update the technote with what I find.
There's been some real Spinal-Tap-esque movement in the Gateway API space since we last looked. kgateway.dev (formerly "Gloo"), which we initially dismissed as being just another Envoy wrapper with a bunch of LLM-related words added to the docs has split into two products: kgateway.dev and agentgateway.dev. kgateway seems like a better version of the Envoy Gateway:

It is fully compliant with the Gateway API spec. Envoy Gateway is not

It is about to add downstream response header passing to it's external auth functionality. Envoy Gateway has a 2-year-old issue without much activity

kgateway does better on these Gateway API benchmarks (which are admittedly created by someone with a stake in kgateway/agentgateway), in speed, design, and "doesn't throw errors"

Most of the LLM-related stuff has been moved to agentgateway.dev, which seems to be a completely new proxy written in Rust, plus the Gateway API CRDs to configure it. There is a ton of highly specific AI/LLM functionality that we do not need now. BUT: it seems to offer everything that we do need as well.
kgateway is a CNCF sandbox project now, agentgateway has been accepted by the Linux Foundation. Both appear to be somehow related with solo.io, though both appear to be legit free and open source, at least for now.

## How to install

https://kgateway.dev/docs/envoy/latest/quickstart/
kgateway.dev/docs/envoy/latest/security/extauth/byo-ext-auth-service/http/

1. Start cloudprovider-kind: `pitchfork start --all`
1. kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/standard-install.yaml
1. helm upgrade -i kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds --create-namespace --namespace kgateway-system --version v2.3.6 --set controller.image.pullPolicy=Always
1. helm upgrade -i kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --namespace kgateway-system --version v2.3.6 --set controller.image.pullPolicy=Always

## Agentgateway

* On 2026-08-04, the container registry that servers the `agentgateway` images was returning a 522: https://cr.agentgateway.dev/v2/auth?scope=repository%3Acontroller%3Apull&service=cr.agentgateway.dev was returning a 522
