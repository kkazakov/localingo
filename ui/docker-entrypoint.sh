#!/bin/sh
envsubst '${API_KEY}' < /etc/nginx/templates/index.html.template > /usr/share/nginx/html/index.html
