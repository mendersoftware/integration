#!/bin/bash
set -e

# this entry point should be called with two arguments: <branch> and <tenant token>

if [ ! -z "$DEBUG" ]; then
    set -x -u
else
    set -u
fi

BRANCH=$1
TENANT_ID=$2
TENANT_TOKEN=$3
INTEGRATION_URL=https://github.com/mendersoftware/integration/tree/"$BRANCH"
S3_URL=https://s3.amazonaws.com/hosted-mender-artifacts-onboarding

STATUS_CODE=$(curl --output /dev/null -s --write-out "%{http_code}" "$INTEGRATION_URL")

if [ "$STATUS_CODE" -ne 200 ]; then
    echo "$BRANCH does not look valid, grabbing $INTEGRATION_URL failed."
    exit 1
fi

echo "Preparing images for branch: $BRANCH for $TENANT_ID, with tenant token: $TENANT_TOKEN"

URLS=(
        https://d1b0l86ne08fsf.cloudfront.net/"$BRANCH"/beaglebone/beaglebone_release_1_"$BRANCH".mender
        https://d1b0l86ne08fsf.cloudfront.net/"$BRANCH"/beaglebone/beaglebone_release_2_"$BRANCH".mender
        https://d1b0l86ne08fsf.cloudfront.net/"$BRANCH"/beaglebone/mender-beaglebone_"$BRANCH".sdimg.gz
        https://d1b0l86ne08fsf.cloudfront.net/"$BRANCH"/vexpress-qemu/vexpress_release_1_"$BRANCH".mender
        https://d1b0l86ne08fsf.cloudfront.net/"$BRANCH"/vexpress-qemu/vexpress_release_2_"$BRANCH".mender
)

if [ ! -d downloaded-images ]; then
    mkdir downloaded-images
else
   rm -f downloaded-images/*
fi

for url in "${URLS[@]}"
do
    (cd downloaded-images && curl  -O -J "$url")
    if [[ "$url" == *.gz ]]; then
      (cd downloaded-images && gunzip ./*.gz)
    fi
done

LINKS_URL="$S3_URL"/"$TENANT_ID"/links.json
STATUS_CODE=$(curl --output /dev/null -s --write-out "%{http_code}" "$LINKS_URL")

if [ "$STATUS_CODE" -ne 200 ]; then
    echo '{"links":{}}' | jq . > links.json
else
    curl  -O -J "$LINKS_URL"
fi

images=(downloaded-images/*)
for image in "${images[@]}"
do
    ./add_tenant_token.sh "$image" "$TENANT_TOKEN"
    (
      cd output
      FILENAME=$(ls)
      gzip "$FILENAME"
      FILENAME="$FILENAME".gz
      URL="$S3_URL"/"$TENANT_ID"/"$FILENAME"
      aws s3api put-object --acl "public-read" --bucket "hosted-mender-artifacts-onboarding" --key "$TENANT_ID"/"$FILENAME" --body "$FILENAME" --tag "tenant_id=$TENANT_ID"
      jq --arg branch "$BRANCH" '.links[$branch] |= . + { "'"$FILENAME"'":"'"$URL"'" }' ../links.json > /tmp/json; cp /tmp/json ../links.json
      cd -
      rm output/*
    )
done

aws s3api put-object --acl "public-read" --bucket "hosted-mender-artifacts-onboarding" --key "$TENANT_ID"/links.json --body links.json --tag "tenant_id=$TENANT_ID"
