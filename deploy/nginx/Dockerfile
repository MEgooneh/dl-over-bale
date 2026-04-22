FROM nginx:1.27-alpine

RUN apk add --no-cache apache2-utils

COPY deploy/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY deploy/nginx/10-generate-real-ip.sh /docker-entrypoint.d/10-generate-real-ip.sh
COPY deploy/nginx/20-generate-htpasswd.sh /docker-entrypoint.d/20-generate-htpasswd.sh

RUN chmod +x /docker-entrypoint.d/10-generate-real-ip.sh /docker-entrypoint.d/20-generate-htpasswd.sh
