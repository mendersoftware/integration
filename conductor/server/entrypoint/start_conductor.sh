#!/bin/bash -e

CONDUCTOR=${CONDUCTOR="http://localhost:8080"}

echo "-- conductor API is at ${CONDUCTOR}"

# start conductor
/app/startup.sh &

# wait for conductor
tries=0
while [ "$tries" -lt 20 ]; do
    if ! curl -f "${CONDUCTOR}/api/metadata/taskdefs" > /dev/null 2>&1 ; then
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
    /srv/conductor-load --conductor-address "${CONDUCTOR}" -t task "$task"
done

# load workflow definitions
for workflow in /srv/workflows/*.json; do
    echo "-- loading workflow $workflow"
    /srv/conductor-load --conductor-address "${CONDUCTOR}" -t workflow "$workflow"
done

# load event definitions
for event in /srv/events/*.json; do
    echo "-- loading event $event"
    /srv/conductor-load --conductor-address "${CONDUCTOR}" -t event "$event"
done

wait
