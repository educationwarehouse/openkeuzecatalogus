#!/usr/bin/env bash

set -euo pipefail

heartbeat_file=/tmp/pgq-heartbeat

[[ -f "$heartbeat_file" ]] || exit 1
(( $(date +%s) - $(stat -c %Y "$heartbeat_file") < 120 ))
