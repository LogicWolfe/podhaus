FROM alpine:3.8

ARG RTORRENT_VER=0.9.7
ARG LIBTORRENT_VER=0.13.7
ARG MEDIAINFO_VER=18.12
ARG FLOOD_VER=master
ARG BUILD_CORES

ENV UID=1000 GID=1000 \
    FLOOD_SECRET=supersecret \
    WEBROOT=/ \
    RTORRENT_SCGI=0 \
    PKG_CONFIG_PATH=/usr/local/lib/pkgconfig

RUN NB_CORES=${BUILD_CORES-`getconf _NPROCESSORS_CONF`} 
RUN apk -U upgrade 
RUN apk add -t build-dependencies \
    build-base \
    git \
    libtool \
    automake \
    autoconf \
    wget \
    tar \
    xz \
    zlib-dev \
    cppunit-dev \
    libressl-dev \
    ncurses-dev \
    curl-dev \
    binutils \
    linux-headers 
RUN apk add \
    ca-certificates \
    curl \
    ncurses \
    libressl \
    gzip \
    zip \
    zlib \
    s6 \
    su-exec \
    python \
    nodejs \
    nodejs-npm \
    unrar \
    findutils 
WORKDIR /tmp
RUN mkdir libtorrent rtorrent
RUN git clone https://github.com/mirror/xmlrpc-c.git 
RUN git clone https://github.com/Rudde/mktorrent.git 
WORKDIR /tmp/mktorrent
RUN  make -j ${NB_CORES} && make install 
WORKDIR /tmp/xmlrpc-c/advanced
RUN  ./configure && make -j ${NB_CORES} && make install 
WORKDIR /tmp/libtorrent
RUN wget -qO- https://github.com/rakshasa/libtorrent/archive/v${LIBTORRENT_VER}.tar.gz | tar xz --strip 1 
RUN ./autogen.sh && ./configure && make -j ${NB_CORES} && make install 
WORKDIR /tmp/rtorrent
RUN wget -qO- https://github.com/rakshasa/rtorrent/releases/download/v${RTORRENT_VER}/rtorrent-${RTORRENT_VER}.tar.gz | tar xz --strip 1 
RUN ./autogen.sh && ./configure --with-xmlrpc-c && make -j ${NB_CORES} && make install 
WORKDIR /tmp
RUN wget -q http://mediaarea.net/download/binary/mediainfo/${MEDIAINFO_VER}/MediaInfo_CLI_${MEDIAINFO_VER}_GNU_FromSource.tar.gz 
RUN wget -q http://mediaarea.net/download/binary/libmediainfo0/${MEDIAINFO_VER}/MediaInfo_DLL_${MEDIAINFO_VER}_GNU_FromSource.tar.gz 
RUN tar xzf MediaInfo_DLL_${MEDIAINFO_VER}_GNU_FromSource.tar.gz 
RUN tar xzf MediaInfo_CLI_${MEDIAINFO_VER}_GNU_FromSource.tar.gz 
RUN cd /tmp/MediaInfo_DLL_GNU_FromSource && ./SO_Compile.sh 
RUN cd /tmp/MediaInfo_DLL_GNU_FromSource/ZenLib/Project/GNU/Library && make install 
RUN cd /tmp/MediaInfo_DLL_GNU_FromSource/MediaInfoLib/Project/GNU/Library && make install 
RUN cd /tmp/MediaInfo_CLI_GNU_FromSource && ./CLI_Compile.sh 
RUN cd /tmp/MediaInfo_CLI_GNU_FromSource/MediaInfo/Project/GNU/CLI && make install 
RUN strip -s /usr/local/bin/rtorrent 
RUN strip -s /usr/local/bin/mktorrent 
RUN strip -s /usr/local/bin/mediainfo 
RUN ln -sf /usr/local/bin/mediainfo /usr/bin/mediainfo
RUN git clone https://github.com/LogicWolfe/flood /usr/flood
WORKDIR /usr/flood
RUN git checkout test-disable-auth
RUN npm install && npm cache clean --force 

RUN ls

COPY rootfs /

RUN chmod +x /usr/local/bin/* /etc/s6.d/*/* /etc/s6.d/.s6-svscan/* 
RUN npm run build
RUN chown -R $UID:$GID /home/torrent /tmp /usr/flood /etc/s6.d

VOLUME /data /flood-db

EXPOSE 3000 49184 49184/udp

LABEL description="BitTorrent client with WebUI front-end" \
      rtorrent="rTorrent BiTorrent client v$RTORRENT_VER" \
      libtorrent="libtorrent v$LIBTORRENT_VER" \
      maintainer="Wonderfall <wonderfall@targaryen.house>"

CMD ["run.sh"]