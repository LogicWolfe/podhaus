# Set the base image to plexpass
# This automatically pulls the latest plexpass plex version
# every time the containers are run or restarted.
FROM plexinc/pms-docker:plexpass

# Install Mesa libraries for GPU transcoding
RUN \
  apt-get update && \
  apt-get -y install libgl1-mesa-glx libgl1-mesa-dri && \
  rm -rf /var/lib/apt/lists/*
