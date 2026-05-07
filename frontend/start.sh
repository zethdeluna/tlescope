#!/bin/sh
set -e

# Read the first nameserver from /etc/resolv.conf.
# nginx requires IPv6 addresses wrapped in square brackets (e.g. [fd12::10]),
# so detect colons and add brackets when needed.
RESOLVER=$(awk '/^nameserver/{
    ip = $2
    if (ip ~ /:/) ip = "[" ip "]"
    print ip
    exit
}' /etc/resolv.conf)

export NGINX_LOCAL_RESOLVERS="${RESOLVER:-127.0.0.11}"

envsubst '${BACKEND_URL} ${NGINX_LOCAL_RESOLVERS}' \
    < /etc/nginx/templates/default.conf.template \
    > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
