#!/bin/sh
# Sets up pi for llm.pod.haus: installs the llm-pod-haus provider extension as
# llm-pod-haus.ts in pi's extensions directory and changes nothing else of
# pi's. The extension signs in by itself, through pi's /login.
#
# Meant for `curl -fsSL https://llm.pod.haus/setup/pi.sh | sh`. The shell then
# reads this script from its standard input, so nothing here may read standard
# input. Everything runs from main, called on the last line, so a download cut
# short runs nothing.
#
# LLM_POD_HAUS_URL replaces https://llm.pod.haus as the address files come
# from. PI_CODING_AGENT_DIR, pi's own setting, replaces ~/.pi/agent as pi's
# directory.

set -eu

fail() {
	printf '%s\n' "$1" >&2
	exit 1
}

# Downloads $1 to $2 with mode $3. The file in place is replaced only once the
# new one has arrived whole.
fetch() {
	if ! curl -fsSL -o "$2.part" "$1"; then
		rm -f "$2.part"
		fail "download failed: $1"
	fi
	chmod "$3" "$2.part"
	mv -f "$2.part" "$2"
}

main() {
	command -v curl >/dev/null 2>&1 || fail "curl not found"
	extensions="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/extensions"
	mkdir -p "$extensions"
	fetch "${LLM_POD_HAUS_URL:-https://llm.pod.haus}/setup/llm-pod-haus.ts" "$extensions/llm-pod-haus.ts" 644
	command -v pi >/dev/null 2>&1 || printf '%s\n' "pi not found" >&2
	printf '%s\n' "In pi:" "  /login llm-pod-haus" "  /model"
}

main
