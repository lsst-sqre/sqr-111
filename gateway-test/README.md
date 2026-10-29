# gateway-test

A set of code and Kubernetes config to test features of multiple Kubernetes ingress and gateway controllers.

## Prerequisites

* Docker is installed and on your path
* [mise](https://mise.jdx.dev) is installed and on your path

## Running the tests

1. Provision a local [kind](https://kind.sigs.k8s.io) Kubernetes cluster and install all of the controllers, apps, and config into it with `mise rebuild`
1. Run the tests against all gateways with `mise test`
1. Run a test against a single gateway/ingress controller with `mise test <controller name>`. `mise test --help` will show the available values.
