# FROM ubuntu:22.04
# RUN apt-get update
# RUN apt-get install -y \
#   build-essential git autotools-dev autoconf automake libtool gettext gawk \
#   gperf bison flex libconfuse-dev libunistring-dev libsqlite3-dev \
#   libavcodec-dev libavformat-dev libavfilter-dev libswscale-dev libavutil-dev \
#   libasound2-dev libmxml-dev libgcrypt20-dev libavahi-client-dev zlib1g-dev \
#   libevent-dev libplist-dev libsodium-dev libjson-c-dev libwebsockets-dev \
#   libcurl4-openssl-dev libprotobuf-c-dev
# RUN git clone https://github.com/owntone/owntone-server.git
# WORKDIR owntone-server
# RUN autoreconf -i
# RUN ./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var --enable-install-user
# RUN make
# RUN make install
# CMD sleep 300
# CMD ["/usr/sbin/owntone"]

FROM dwinks/owntone-aarch64
CMD sleep 300