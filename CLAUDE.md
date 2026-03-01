# PodHaus

Docker container infrastructure for home servers deployed to podhaus (pod.haus) and pinelake (pinelake.haus).

## Architecture

- Each service has its own directory containing a `run` script and optionally a `Dockerfile` and config files
- Containers are started with `sudo docker run` via individual `run` scripts — not docker-compose
- Container names always match their directory name (derived via `${PWD##*/}`)
- Root-level management scripts (`build`, `stop`, `connect`, `restart`) are symlinked into service directories

## Conventions

### Run scripts

Every `run` script follows this pattern:
```bash
#!/bin/bash
source $( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )/../before_run
sudo docker run \
  --detach \
  --name <service-name> \
  --restart=unless-stopped \
  ...
```

`before_run` exports variables from `environment` and `secrets` files. All run scripts are bash.

### Networking

- `dockernet`: bridge network at 172.16.42.0/24 for inter-container communication
- Services needing device access or many ports use `--network=host`
- nginx reverse-proxies services on `*.pod.haus` subdomains

### Environment switching

The active environment is determined by which file is copied to `environment` and which secrets are decrypted:
```
cp environment.podhaus environment
./decrypt_secrets secrets.podhaus.gpg
```

Both `environment` and `secrets` are git-ignored.

## Key files

- `before_run` — sources environment and secrets, used by all run scripts
- `build` — builds a Docker image tagged with the directory name
- `stop` — stops and removes a container by directory name
- `connect` — exec into a running container (tries bash, falls back to sh)
- `restart` — calls stop then run
- `create_network` — creates the dockernet bridge
- `create_symlinks` — symlinks management scripts into service directories
- `encrypt_secrets` / `decrypt_secrets` — GPG symmetric encryption for secrets files

## When adding a new service

1. Create a directory named after the service
2. Add a `run` script following the pattern above
3. Add a `Dockerfile` if a custom image is needed
4. Run `create_symlinks` to set up management script symlinks
5. Add nginx config in `nginx/conf.d/` if the service needs a subdomain
6. Document the service in README.md
