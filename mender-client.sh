#!/bin/bash

HERE="$(dirname "$0")"
echo "The present working directory is $HERE"

MENDER_TENANT_TOKEN=${MENDER_TENANT_TOKEN}

MENDER_SERVER_URL=${MENDER_SERVER_URL:-"https://hosted.mender.io"}
MENDER_DEVICE_TYPE=${DEVICE_TYPE:-"bash-client"}

# This variable is mutable
MENDER_ARTIFACT_NAME="release-v1"

# extra curl option setting client cert/key for mTLS - if specified
# used only for auth_requests
CLIENT_CERT_OPT=${MENDER_CLIENT_CERT:+"--cert $MENDER_CLIENT_CERT --key $MENDER_CLIENT_KEY"}

function show_help() {
  cat << EOF
mender-client.sh

This is simple Mender client written in bash and was primarily developed to
demonstrate the device facing API of the Mender server and what the bare
minimum is to implement a custom Mender client, e.g in a MCU.

The following workflows are covered (in the order they are performed):

    1. device authorization
    2. pushing inventory
    3. checking for deployments
    4. downloading deplyoment
    5. updating deployment status on the server

Usage: ./$0 COMMAND [options]

Options:
  -t, --token                 - Mender server tenant token
  -d, --device-type           - Device type string to report to the server

EOF
}

function show_help_keys() {
  cat << EOF
You need to generate a key-pair to be able to authorize the "device".

You can generate a key-pair using the following commands:

    mkdir keys
    openssl genpkey -algorithm RSA -out keys/private.key -pkeyopt rsa_keygen_bits:3072
    openssl rsa -in keys/private.key -out keys/private.key
    openssl rsa -in keys/private.key -out keys/public.key -pubout

EOF
}

function normalize_data() {
    echo "$1" | tr -d '\n' | tr -d '\r'
}

function generate_signature() {
  # Request signature, computed as 'BASE64(SIGN(device_private_key, SHA256(request_body)))'.
  #
  # It is very important to clean up any newlines (\r or \n) in the request body
  # here as this will be removed when the request is made and if they are not
  # cleaned up the signature will invalid
  normalize_data "$(cat auth.json)" | \
    openssl dgst -sha256 -sign $HERE/keys/private.key | openssl base64 -A
}

function auth_request_status() {
  x_men_signature=$(generate_signature)
  curl $CLIENT_CERT_OPT -iv -k -s -o /dev/null -w '%{http_code}' \
    -H "Content-Type: application/json" \
    -H "X-MEN-Signature: ${x_men_signature}" \
    --data "@auth.json" \
    ${MENDER_SERVER_URL_AUTHREQS}/api/devices/v1/authentication/auth_requests
}

# $1 - path to data JSON file for auth request
function wait_for_authorized() {
  # Replace newlines with \n
  pubkey=$(awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}' $HERE/keys/public.key)
  hexchars="0123456789ABCDEF"
  end=$( for i in {1..6} ; do echo -n ${hexchars:$(( $RANDOM % 16 )):1} ; done | sed -e 's/\(..\)/:\1/g' )

  # Prepare authorization request
  cat <<- EOF > auth.json
{
    "id_data": "{ \"mac\": \"00:11:22${end}\"}",
    "pubkey": "${pubkey}",
    "tenant_token": "${MENDER_TENANT_TOKEN}"
}
EOF

  while true; do
    echo "Send authorization request."
    echo "Please authorization the device on the server for it to proceed"
    status_code=$(auth_request_status)
    if [ "$status_code" == "200" ]; then
        echo "Client has been authorized"
      break;
    fi
    sleep 5
  done
}

function get_jwt() {
  x_men_signature=$(generate_signature)
  curl $CLIENT_CERT_OPT -k \
    -H "Content-Type: application/json" \
    -H "X-MEN-Signature: ${x_men_signature}" \
    --data "@auth.json" \
    ${MENDER_SERVER_URL_AUTHREQS}/api/devices/v1/authentication/auth_requests
}

function send_inventory() {
  cat <<- EOF > inventory.json
[
    {
      "name":"device_type",
      "value":"${MENDER_DEVICE_TYPE}"
    },
    {
      "name":"artifact_name",
      "value":"${MENDER_ARTIFACT_NAME}"
    },
    {
      "name":"kernel",
      "value":"$(uname -a)"
    }
]
EOF

  curl -k \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $JWT" \
    --data "@inventory.json" \
    -X PATCH \
    ${MENDER_SERVER_URL}/api/devices/v1/inventory/device/attributes
}

function deployments_status() {
  curl -k -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $JWT" \
    -X GET \
    "${MENDER_SERVER_URL}/api/devices/v1/deployments/device/deployments/next?artifact_name=${MENDER_ARTIFACT_NAME}&device_type=${MENDER_DEVICE_TYPE}"
}

function check_deployment() {
  while true; do
    echo "Check for deployments..."
    status_code=$(deployments_status)
    if [ "$status_code" == "200" ]; then
      echo "There is a deployments waiting for us"
      break;
    fi
    sleep 5
  done
}

function get_deplyoment() {
  curl -k \
    -H "Authorization: Bearer $JWT" \
    -X GET \
    "${MENDER_SERVER_URL}/api/devices/v1/deployments/device/deployments/next?artifact_name=${MENDER_ARTIFACT_NAME}&device_type=${MENDER_DEVICE_TYPE}"
}

# $1 - deployment id
# $2 - enum (installing, downloading, rebooting, success, failure, already-installed)
function set_deplyoment_status() {
  echo "${1}: state changed to: ${2}"
  curl -k \
    -H "Authorization: Bearer $JWT" \
    -H "Content-Type: application/json" \
    -d "{\"status\":\"${2}\"}" \
    -X PUT \
    "${MENDER_SERVER_URL}/api/devices/v1/deployments/device/deployments/${1}/status"
}

while (( "$#" )); do
  case "$1" in
    -t | --token)
      MENDER_TENANT_TOKEN="${2}"
      shift 2
      ;;
    -d | --device-type)
      MENDER_DEVICE_TYPE="${2}"
      shift 2
      ;;
    *)
      show_help
      exit 1
      ;;
  esac
done

if [ -z "${MENDER_TENANT_TOKEN}" ] || [ -z "${MENDER_TENANT_TOKEN}" ]; then
  show_help
  exit 1
fi

if [ ! -e $HERE/keys/private.key ] || [ ! -e $HERE/keys/public.key ]; then
  show_help_keys
  exit 1
fi

echo "Prepare authorization request"
wait_for_authorized

# Once we are are authorized with the server we can download a time limited
# JSON Web Token which we will be used for all subsequent API calls.

echo "Fetch JSON Web Token"
JWT=$(get_jwt)

echo "Send inventory data..."
send_inventory

while true; do
  check_deployment

  # Handle deployment

  deployment_json=$(get_deplyoment)

  deployment_id=$(jq -r '.id' <<< ${deployment_json})
  deployment_url=$(jq -r '.artifact.source.uri' <<< ${deployment_json})

  echo "Downloading artifact: ${deployment_url}"
  set_deplyoment_status "${deployment_id}" "downloading"

  # Here one would decompress the artifact and write it to the storage medium
  wget -O /dev/null ${deployment_url}

  # Here one would prepare the bootloader flags prior to restarting and try
  # booting the new image
  set_deplyoment_status "${deployment_id}" "installing"
  sleep 10

  # Reboot device :)
  set_deplyoment_status "${deployment_id}" "rebooting"
  sleep 10

  # Here one would do a sanity check if the update was successful, e.g the
  # minimum success criteria could be that the device boots and is able to
  # re-connect to the Mender server

  # Marking the update complete, optionally one could trigger a roll-back here
  # and later on report status "failure"
  set_deplyoment_status "${deployment_id}" "success"

  # Update artifact name
  MENDER_ARTIFACT_NAME=$(jq -r '.artifact.artifact_name' <<< ${deployment_json})

  # Push inventory so that artifact_name change is reflected on the server
  send_inventory
done
