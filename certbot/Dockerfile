FROM python:latest
RUN pip install certbot
RUN pip install certbot-dns-dnsimple
RUN mkdir /srv/certbot
ARG dnsimple_api_token
RUN echo "dns_dnsimple_token = $dnsimple_api_token" > /srv/certbot/dnsimple.ini
RUN chmod 0600 /srv/certbot/dnsimple.ini
WORKDIR /srv/certbot
CMD while true; do \
  certbot certonly \
    --non-interactive \
    --expand \
    --agree-tos \
    --keep-until-expiring \
    --dns-dnsimple \
    --dns-dnsimple-credentials /srv/certbot/dnsimple.ini \
    -d torrent.pod.haus \
    -d unifi.pod.haus;\
    -d reviewer.pod.haus;\
  sleep 86400; done