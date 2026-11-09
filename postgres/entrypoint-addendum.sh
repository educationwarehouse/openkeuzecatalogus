#!/bin/sh
# Layer postgres/addendum.conf onto the config the base image actually reads.
#
# Fresh clusters get `include = '/etc/postgresql/postgresql.conf'` from
# postgresql.conf.sample (see the Dockerfile); clusters initialized before that
# still have a postgresql.conf without it, so append it once here. Without this
# the bind mount is silently ignored and shared_preload_libraries stays empty.
set -eu

addendum=/etc/postgresql/postgresql.conf
main_config="${PGDATA:-/var/lib/postgresql/data}/postgresql.conf"

if [ -f "$main_config" ]; then
    grep -qF "include = '$addendum'" "$main_config" ||
        printf "\ninclude = '%s'\n" "$addendum" >>"$main_config"
fi

exec docker-entrypoint.sh "$@"
