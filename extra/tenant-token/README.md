# Tenant Token tool in a Docker container

#### run with:

```
docker build -t tenanttoken -f Dockerfile .
docker run --privileged -e AWS_ACCESS_KEY=<access-key> -e AWS_SECRET_KEY=<secret-key> -v <local-img>:/filename.abc tenanttoken filename.abc <tenant-token>
```
