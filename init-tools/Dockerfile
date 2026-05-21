# Shared init-container base image for podhaus stacks.
#
# Carries the tools that init containers across the fleet need to render
# config files from templates + secrets at deploy time:
#   - gettext (envsubst): variable substitution into JSON/XML/YAML templates
#   - python3:            for stacks whose merge logic is a python script
#                         (currently just plex's Preferences.xml merge)
#   - curl + jq:          HTTP + JSON for inits that hit external APIs
#                         (e.g. tailscale-cleanup's tailnet ghost pruner)
#
# Built locally on each Periphery via inline `build:` directives in the
# consumer stacks' compose files (init-tools doesn't have its own stack —
# it's pure tooling, no service to run).
#
# Add new tools here as more init containers come online; layer cache means
# adding a tool is fast on rebuild and the resulting image stays small.

FROM alpine:latest

RUN apk add --no-cache gettext python3 curl jq
