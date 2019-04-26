FROM python:latest
RUN pip install certbot
RUN pip install certbot-dns-dnsimple
RUN mkdir /srv/certbot
ARG dnsimple_api_token
RUN echo "dns_dnsimple_token = $dnsimple_api_token" > /srv/certbot/dnsimple.ini
RUN chmod 0600 /srv/certbot/dnsimple.ini
WORKDIR /srv/certbot