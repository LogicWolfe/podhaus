FROM nginx
RUN apt-get update && apt-get install --yes procps curl net-tools
COPY conf.d/* /etc/nginx/conf.d/
