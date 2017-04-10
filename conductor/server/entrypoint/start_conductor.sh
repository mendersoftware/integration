#!/bin/bash -e

# start conductor
/app/startup.sh &

# wait for conductor
sleep 60

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
