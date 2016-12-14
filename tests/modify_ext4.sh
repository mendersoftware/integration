#!/bin/bash
set -eu

MENDER_CONF="/etc/mender/mender.conf"
TEMPFILE=$(mktemp)
e2cp "$IMAGE_TO_EDIT":"$MENDER_CONF" "$TEMPFILE"

sed -i 's/.*UpdatePollIntervalSeconds.*/\  "UpdatePollIntervalSeconds\": 2,/g' "$TEMPFILE"
sed -i 's/.*InventoryPollIntervalSeconds.*/\  "InventoryPollIntervalSeconds\": 2,/g' "$TEMPFILE"

e2cp "$TEMPFILE" "$IMAGE_TO_EDIT":"$MENDER_CONF"
