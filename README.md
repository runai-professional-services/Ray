# Ray on Kubernetes with KubeRay

This repository contains YAML configuration files for deploying Ray on a runai using the KubeRay operator.

## Prerequisites

Before you begin, ensure you have the following:

- A Kubernetes cluster
- Helm package manager installed
- `kubectl` command-line tool installed and configured to communicate with your cluster

## Installation

1. Install the KubeRay operator using Helm:

helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update
helm install kuberay-operator kuberay/kuberay-operator --namespace ray-system --create-namespace


2. Clone this repository:

git clone https://github.com/your-username/your-repo.git
cd your-repo


## Usage

1. Create a RayCluster by applying the `raycluster.yaml` file:

kubectl apply -f raycluster.yaml

This will create a RayCluster named `sample-raycluster` in the `runai-test` namespace.

2. Create a RayJob by applying the `rayjob.yaml` file:

kubectl apply -f rayjob.yaml

This will create a RayJob named `sample-rayjob` in the `runai-test` namespace.

3. Access the Ray Dashboard:

- Get the name of the Ray head service:

  ```
  kubectl get service -n runai-test
  ```

  Look for a service with a name like `<rayjob-name>-raycluster-<hash>-head-svc`.

- Port forward the Ray head service to your local machine:

  ```
  kubectl port-forward service/<ray-head-service-name> 8265:8265 -n runai-test
  ```

  Replace `<ray-head-service-name>` with the actual service name from the previous step.

- Open a web browser and navigate to `http://localhost:8265` to access the Ray dashboard.

## Configuration

The `raycluster.yaml` and `rayjob.yaml` files contain the configurations for the RayCluster and RayJob, respectively. You can modify these files to adjust the resources, replicas, and other parameters according to your requirements.

## Cleanup

To delete the RayJob and RayCluster, use the following commands:

kubectl delete -f rayjob.yaml
kubectl delete -f raycluster.yaml








