#!/bin/bash -e

# start conductor
/app/startup.sh &

# wait for conductor
tries=0
while [ "$tries" -lt 20 ]; do
    if ! curl -f http://localhost:8080/api/metadata/taskdefs > /dev/null 2>&1 ; then
        tries=$((tries + 1))
        echo "-- $(date) waiting for conductor, attempt ${tries}"
        sleep 5
    else
        up=1
        break
    fi
done

if [ "$up"  != "1" ] ; then
    echo "-- $(date) conductor still down, exiting"
    exit 1
fi

shopt -s nullglob

# load task definitions
for task in /srv/tasks/*.json; do
    echo "-- loading task $task"
    curl -f -v -X POST -H "Content-Type: application/json" \
         http://localhost:8080/api/metadata/taskdefs \
         -d @$task
done

# load workflow definitions
for workflow in /srv/workflows/*.json; do
    echo "-- loading workflow $workflow"
    curl -f -v -X POST -H "Content-Type: application/json" \
         http://localhost:8080/api/metadata/workflow \
         -d @$workflow
done

wait
