#!/bin/sh
# Sets up Claude Code for llm.pod.haus: installs the sign-in token command as
# ~/.local/bin/llm-token and the launcher as ~/.local/bin/claude-local, then
# runs the token command once, so the first sign-in happens now, while the
# setup page is still open in the browser.
#
# Meant for `curl -fsSL https://llm.pod.haus/setup/claude.sh | sh`. The shell
# then reads this script from its standard input, so nothing here may read
# standard input. Everything runs from main, called on the last line, so a
# download cut short runs nothing.
#
# LLM_POD_HAUS_URL replaces https://llm.pod.haus as the address files come
# from. The name is this service's alone: a generic one could already be set
# for another tool, whose server would then be sent a fresh key.

set -eu

fail() {
	printf '%s\n' "$1" >&2
	exit 1
}

require() {
	command -v "$1" >/dev/null 2>&1 || fail "$1 not found"
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

# How to start claude-local from the directory $1: by name when $1 is on PATH,
# by its full path otherwise.
start_command() {
	case ":$PATH:" in
	*":$1:"*) printf '%s\n' claude-local ;;
	*)
		printf '%s\n' "$1 not on PATH" >&2
		printf '%s\n' "$1/claude-local"
		;;
	esac
}

main() {
	require python3
	require curl
	setup="${LLM_POD_HAUS_URL:-https://llm.pod.haus}/setup"
	bin="$HOME/.local/bin"
	mkdir -p "$bin"
	fetch "$setup/llm-token.py" "$bin/llm-token" 755
	fetch "$setup/claude-local" "$bin/claude-local" 755
	start=$(start_command "$bin")
	command -v claude >/dev/null 2>&1 || printf '%s\n' "claude not found" >&2
	# The token goes nowhere: Claude Code asks the command for it when needed.
	# Its sign-in link and any failure go to the terminal on standard error.
	"$bin/llm-token" </dev/null >/dev/null || fail "sign-in failed"
	printf 'Start: %s\n' "$start"
}

main
