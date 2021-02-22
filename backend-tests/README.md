# Back-end integration tests for Mender

This folder contains the back-end integration tests for the Mender Product.

You can start the tests running the `run` script:

```bash
$ ./run -s enterprise
```

See the help for more information about the available options:

```bash
$ ./run --help
```

## Run the back-end tests in the staging environment running in Kubernetes

It is possible to run the back-end tests targeting the staging environment running in Kubernetes.
You can either run them using GitLab (recommended) or from your local environment.

### Run the back-end tests using GitLab

To run the tests in GitLab, [start a new pipeline in GitLab](https://gitlab.com/Northern.tech/Mender/integration/-/pipelines/new), select your branch (`staging`, for example) and set the `RUN_TESTS_STAGING` variable to `true`.

### Run the back-end tests from your local environment

In order to do it, you need to export the following environment variables:

```bash
$ export K8S="staging"
$ export AWS_ACCESS_KEY_ID="<aws-access-key>"
$ export AWS_SECRET_ACCESS_KEY="<aws-access-key>"
$ export AWS_DEFAULT_REGION="us-east-1"
$ export AWS_EKS_CLUSTER_NAME="hosted-mender-staging"
$ export GATEWAY_HOSTNAME="staging.hosted.mender.io"
```

The values of the variables follow:

* **K8S** contains the name of the namespace where the Mender product is running in the Kubernetes cluster;
* **AWS_ACCESS_KEY_ID** and **AWS_SECRET_ACCESS_KEY** are the AWS access key and secret, used to authenticate to the EKS cluster;
* **AWS_DEFAULT_REGION** contains the region where the EKS cluster is running;
* **AWS_EKS_CLUSTER_NAME** contains the name of the EKS cluster;
* **GATEWAY_HOSTNAME** determines the Mender API gateway's public host name, accessible via HTTPS, to call public API end-points.

You can now start the test using the `run` script.
