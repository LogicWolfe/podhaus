FROM python:latest
RUN pip install certbot
RUN pip install certbot-dns-cloudflare
RUN mkdir /srv/certbot
ARG cloudflare_api_token
ARG admin_email
ENV ADMIN_EMAIL $admin_email
RUN echo "dns_cloudflare_api_token = $cloudflare_api_token" > /srv/certbot/cloudflare.ini
RUN chmod 0600 /srv/certbot/cloudflare.ini
WORKDIR /srv/certbot
CMD while true; do \
  certbot certonly \
    --non-interactive \
    --expand \
    --agree-tos \
    --email ${ADMIN_EMAIL} \
    --keep-until-expiring \
    --dns-cloudflare \
    --dns-cloudflare-credentials /srv/certbot/cloudflare.ini \
    -d '*.pod.haus' \
    -d pod.haus; \
  sleep 86400; done
