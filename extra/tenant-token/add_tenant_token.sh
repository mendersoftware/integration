#!/bin/bash
set -e

if [ -n "$DEBUG" ]; then
  set -x
fi

REQUIREMENTS=( "jq" "debugfs" "sha256sum" "parted" )
HOSTED_MENDER_URL="https://hosted.mender.io"
OUTPUT_DIR="output/"

function mender_tt {
  local mender_conf_file="/etc/mender/mender.conf"
  local filename=$1
  local tt=$2

  local tmp_dir=$(mktemp -d)
  local jq_argument=$(printf ".TenantToken = \"%s\" | .ServerURL = \"%s\"" "$tt" "$HOSTED_MENDER_URL")
  local tmpfile=$(mktemp)

  tar xf "$filename" -C "$tmp_dir"
  tar xf "$tmp_dir"/data/0000.tar.gz -C "$tmp_dir"/data/

  local foundext4=$(find "$tmp_dir" -iname "*.ext4")
  local ext4filename=$(basename "$foundext4")

  # copy mender.conf file from image
  debugfs -R "dump $mender_conf_file $tmp_dir/mender.conf" $foundext4

  # update JSON with tenant key and hosted mender ServerURL
  jq "$jq_argument" "$tmp_dir/mender.conf" > "$tmpfile"

  # create debugfs script to copy over new mender.conf file
  echo "cd /etc/mender/" > /tmp/tt_script
  echo "rm mender.conf" >> /tmp/tt_script
  echo "write $tmpfile mender.conf" >> /tmp/tt_script
  echo "close" >> /tmp/tt_script

  echo "New config. file is:"
  cat "$tmpfile"

  # write back to image
  debugfs -w -f "/tmp/tt_script" "$foundext4"

  local newsha=$(sha256sum "$foundext4" | head -c 64)
  sed -i "/$ext4filename/d" "$tmp_dir/manifest"
  echo "$newsha  data/0000/$ext4filename" >> "$tmp_dir/manifest"

  # repackage image
  (cd "$tmp_dir"/data && tar czf 0000.tar.gz "$ext4filename")

  # re-create mender artifact

  if [ ! -d $OUTPUT_DIR ]; then
    mkdir $OUTPUT_DIR
  fi

  local new_mender_artifact=$(pwd -P)/$OUTPUT_DIR/$(basename "$filename" .mender)".mender"
  (cd "$tmp_dir"/ && tar cf "$new_mender_artifact" version manifest header.tar.gz data/0000.tar.gz)
  echo
  echo "Mender artifact with specified tenant_token created with filename: $new_mender_artifact"

  rm -rf "$tmp_dir"
  rm "$tmpfile"
}

function sdimg_tt {
  local mender_conf_file="/etc/mender/mender.conf"
  local filename=$1
  local tt=$2

  if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"; exit 1
  fi

  local mount_dir=$(mktemp -d)

  # ugly way to determine start sectors of sdimg
  local start_sectors=$(parted "$filename" "unit s print" | grep -i '^[[:blank:]]\{1,\}[0-9]' | awk '{ print $2}' | tr -d 's')
  read -a start_sectors_array <<< $start_sectors

  local tempfile=$(mktemp)
  local jq_argument=$(printf ".TenantToken = \"%s\" | .ServerURL = \"%s\"" "$tt" "$HOSTED_MENDER_URL")

  # mount every partition, and copy over the mender.conf file
  for s in "${start_sectors_array[@]}"
  do
    sudo mount -o loop,offset=$((s * 512)) "$filename" "$mount_dir"
    if [ -e "$mount_dir""$mender_conf_file" ]; then
      jq "$jq_argument" "$mount_dir""$mender_conf_file" > "$tempfile"
      cp "$tempfile" "$mount_dir""$mender_conf_file"
      echo "new mender.conf added to partition.."
    fi
    sudo umount "$mount_dir"
  done

  echo "created new sdimg with specified tenant token"

  # output new sdimg
  if [ ! -d $OUTPUT_DIR ]; then
    mkdir $OUTPUT_DIR
  fi

  cp $filename $OUTPUT_DIR

  rm -rf "$mount_dir"
  rm "$tempfile"
}

for app in "${REQUIREMENTS[@]}"; do
    type $app >/dev/null
    if [ $? -ne 0 ]; then
      echo "'$app' needs to be installed, try installing it with your system's package manager."; exit 1
    fi
done

if [ $# -ne 2 ]; then
  scriptname=$(basename "$0")
  echo "Usage: $scriptname <file> <tenant_token>"
  echo "Note file can be a .mender artifact file or a .sdimg file"
  echo
  echo "This script modifies *.sdimg/*.mender files by adding a tenant_token entry to the config, and "
  echo "sets the mender server to the Mender Cloud hosted backend"
  echo
  echo "set DEBUG=1 for verbose output"
else
  filename=$1
  tenant_token=$2

  if [ ! -e "$filename" ]; then
    echo "$filename: does not exist, aborting"; exit 1
  fi

  case "$filename" in
    *.mender) mender_tt "$filename" "$tenant_token";;
    *.sdimg)  sdimg_tt "$filename" "$tenant_token";;
    *)        echo "invalid filename, expecting *.sdimg or *.mender ext."; exit 1
esac
fi
