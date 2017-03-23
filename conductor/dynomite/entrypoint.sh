#!/bin/bash

# Start redis server on 22122, read in config
redis-server /etc/redis/redis.conf &

src/dynomite --conf-file=conf/redis_single.yml -v11
