FROM nginx:alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY index.html /etc/nginx/templates/index.html.template
COPY docker-entrypoint.sh /docker-entrypoint.d/40-substitute-html.sh
RUN chmod +x /docker-entrypoint.d/40-substitute-html.sh
