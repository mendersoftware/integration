FROM mendersoftware/api-gateway:master
RUN sed -i -e 's/mender-\(useradm\|inventory\|deployments\|device-auth\|device-adm\|gui\)/mender-\1-2/g' \
               /usr/local/openresty/nginx/conf/nginx.conf
RUN sed -i -e 's/docker\.mender\.io/docker\.mender-failover\.io/g' \
               /usr/local/openresty/nginx/conf/nginx.conf
