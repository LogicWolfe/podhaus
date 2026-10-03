// Runs the extension's PocketId against a stand-in Pocket ID served locally.
//   node --test podhaus.test.ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, test } from "node:test";
import type { OAuthLoginCallbacks } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerExtension, { type Clock, PocketId, systemClock } from "../llm-setup/podhaus.ts";

type TokenAnswer = { status: number; body: Record<string, unknown> };

let server: Server;
let issuer: string;
let tokenAnswers: TokenAnswer[];
let authorizeBody: Record<string, unknown>;
let received: { path: string; form: Record<string, string> }[];

async function readForm(request: IncomingMessage): Promise<Record<string, string>> {
	let text = "";
	for await (const chunk of request) text += chunk;
	return Object.fromEntries(new URLSearchParams(text));
}

before(async () => {
	server = createServer(async (request, response) => {
		const send = (status: number, body: unknown) => {
			response.writeHead(status, { "Content-Type": "application/json" });
			response.end(JSON.stringify(body));
		};
		if (request.url === "/.well-known/openid-configuration") {
			return send(200, {
				device_authorization_endpoint: `${issuer}/api/oidc/device/authorize`,
				token_endpoint: `${issuer}/api/oidc/token`,
			});
		}
		received.push({ path: request.url!, form: await readForm(request) });
		if (request.url === "/api/oidc/device/authorize") return send(200, authorizeBody);
		const answer = tokenAnswers.shift();
		assert.ok(answer, "the stand-in ran out of scripted token answers");
		send(answer.status, answer.body);
	});
	await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
	issuer = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

after(() => server.close());

function reset(tokens: TokenAnswer[], expiresIn = 600) {
	tokenAnswers = tokens;
	received = [];
	authorizeBody = {
		device_code: "DEVICE123",
		user_code: "ABCD-EFGH",
		verification_uri_complete: "https://id.example/device?code=ABCD-EFGH",
		interval: 1,
		expires_in: expiresIn,
	};
}

/** Time that only moves when the flow sleeps, so polling intervals are visible. */
class FakeClock implements Clock {
	time = 1_000_000;
	sleeps: number[] = [];
	now() {
		return this.time;
	}
	async sleep(ms: number) {
		this.sleeps.push(ms);
		this.time += ms;
	}
}

function callbacks(signal?: AbortSignal) {
	const seen = { deviceCodes: [] as unknown[], progress: [] as string[] };
	const value = {
		onDeviceCode: (info: unknown) => seen.deviceCodes.push(info),
		onProgress: (message: string) => seen.progress.push(message),
		onAuth: () => assert.fail("a device flow must not use onAuth"),
		onPrompt: async () => assert.fail("a device flow must not prompt"),
		onSelect: async () => assert.fail("a device flow must not select"),
		signal,
	} as OAuthLoginCallbacks;
	return { value, seen };
}

const pending = { status: 400, body: { error: "authorization_pending" } };
const success = { status: 200, body: { access_token: "ACCESS1", refresh_token: "REFRESH1", expires_in: 3600 } };

test("pending twice, slow_down once, then success", async () => {
	reset([pending, pending, { status: 400, body: { error: "slow_down" } }, success]);
	const clock = new FakeClock();
	const { value, seen } = callbacks();
	const credentials = await new PocketId(issuer, "llm-token", clock).login(value);

	assert.deepEqual(seen.deviceCodes, [
		{
			userCode: "ABCD-EFGH",
			verificationUri: "https://id.example/device?code=ABCD-EFGH",
			intervalSeconds: 1,
			expiresInSeconds: 600,
		},
	]);
	assert.deepEqual(seen.progress, ["Waiting for the sign-in to be approved", "Signed in"]);
	assert.deepEqual(clock.sleeps, [1000, 1000, 1000, 6000], "slow_down adds five seconds");
	assert.equal(credentials.access, "ACCESS1");
	assert.equal(credentials.refresh, "REFRESH1");
	assert.equal(credentials.expires, clock.time + 3600_000 - 5 * 60_000, "expires five minutes early");
	assert.deepEqual(received[0], {
		path: "/api/oidc/device/authorize",
		form: { client_id: "llm-token", scope: "openid email groups" },
	});
	assert.deepEqual(received[1].form, {
		grant_type: "urn:ietf:params:oauth:grant-type:device_code",
		device_code: "DEVICE123",
		client_id: "llm-token",
	});
});

test("denial fails with a plain error", async () => {
	reset([pending, { status: 400, body: { error: "access_denied" } }]);
	await assert.rejects(
		new PocketId(issuer, "llm-token", new FakeClock()).login(callbacks().value),
		{ message: "The sign-in was denied" },
	);
});

test("server-reported expiry fails with a plain error", async () => {
	reset([{ status: 400, body: { error: "expired_token" } }]);
	await assert.rejects(
		new PocketId(issuer, "llm-token", new FakeClock()).login(callbacks().value),
		{ message: "The sign-in link expired before it was approved" },
	);
});

test("link outliving expires_in fails without polling again", async () => {
	reset([pending, pending, pending], 2);
	const clock = new FakeClock();
	await assert.rejects(new PocketId(issuer, "llm-token", clock).login(callbacks().value), {
		message: "The sign-in link expired before it was approved",
	});
	assert.deepEqual(clock.sleeps, [1000, 1000]);
	assert.equal(received.length, 2, "authorize plus one poll, then expiry");
});

test("a Pocket ID server error is raised, not retried", async () => {
	reset([{ status: 503, body: {} }]);
	await assert.rejects(new PocketId(issuer, "llm-token", new FakeClock()).login(callbacks().value), {
		message: "Pocket ID answered 503",
	});
});

test("abort during the wait cancels the sign-in", async () => {
	reset([pending, pending]);
	const controller = new AbortController();
	const flow = new PocketId(issuer, "llm-token", systemClock).login(callbacks(controller.signal).value);
	setTimeout(() => controller.abort(), 100);
	await assert.rejects(flow, { message: "Sign-in cancelled" });
	assert.equal(received.length, 1, "no poll went out before the abort");
});

test("an already aborted signal never reaches Pocket ID", async () => {
	reset([]);
	const controller = new AbortController();
	controller.abort();
	await assert.rejects(new PocketId(issuer, "llm-token", systemClock).login(callbacks(controller.signal).value));
	assert.equal(received.length, 0);
});

test("refresh sends the refresh grant and returns the rotated tokens", async () => {
	reset([{ status: 200, body: { access_token: "ACCESS2", refresh_token: "REFRESH2", expires_in: 3600 } }]);
	const clock = new FakeClock();
	const credentials = await new PocketId(issuer, "llm-token", clock).refresh(
		{ access: "old", refresh: "REFRESH1", expires: 0 },
		new AbortController().signal,
	);
	assert.deepEqual(received[0].form, {
		grant_type: "refresh_token",
		refresh_token: "REFRESH1",
		client_id: "llm-token",
	});
	assert.equal(credentials.access, "ACCESS2");
	assert.equal(credentials.refresh, "REFRESH2");
	assert.equal(credentials.expires, clock.time + 3600_000 - 5 * 60_000);
});

test("a refused refresh token fails with a plain error", async () => {
	reset([{ status: 400, body: { error: "invalid_grant" } }]);
	await assert.rejects(
		new PocketId(issuer, "llm-token", new FakeClock()).refresh(
			{ access: "old", refresh: "stale", expires: 0 },
			new AbortController().signal,
		),
		{ message: "Pocket ID no longer accepts the saved sign-in (invalid_grant). Run /login podhaus" },
	);
});

for (const field of ["device_code", "user_code", "verification_uri_complete", "expires_in"]) {
	test(`a device reply without ${field} names it`, async () => {
		reset([]);
		delete authorizeBody[field];
		await assert.rejects(new PocketId(issuer, "llm-token", new FakeClock()).login(callbacks().value), {
			message: `Pocket ID's reply is missing ${field}`,
		});
		assert.equal(received.length, 1, "nothing was polled");
	});
}

for (const field of ["access_token", "refresh_token", "expires_in"]) {
	const reply = { access_token: "A", refresh_token: "R", expires_in: 3600 };
	delete (reply as Record<string, unknown>)[field];

	test(`a token reply without ${field} names it, at sign-in`, async () => {
		reset([{ status: 200, body: reply }]);
		await assert.rejects(new PocketId(issuer, "llm-token", new FakeClock()).login(callbacks().value), {
			message: `Pocket ID's reply is missing ${field}`,
		});
	});

	test(`a token reply without ${field} names it, at refresh`, async () => {
		reset([{ status: 200, body: reply }]);
		await assert.rejects(
			new PocketId(issuer, "llm-token", new FakeClock()).refresh(
				{ access: "old", refresh: "R0", expires: 0 },
				new AbortController().signal,
			),
			{ message: `Pocket ID's reply is missing ${field}` },
		);
	});
}

test("a field of the wrong type is rejected by name", async () => {
	reset([]);
	authorizeBody.interval = "soon";
	await assert.rejects(new PocketId(issuer, "llm-token", new FakeClock()).login(callbacks().value), {
		message: "Pocket ID's reply has an invalid interval: expected a number",
	});
});

test("a missing interval defaults to five seconds", async () => {
	reset([pending, success]);
	delete authorizeBody.interval;
	const clock = new FakeClock();
	const { value, seen } = callbacks();
	await new PocketId(issuer, "llm-token", clock).login(value);
	assert.deepEqual(clock.sleeps, [5000, 5000]);
	assert.equal((seen.deviceCodes[0] as { intervalSeconds: number }).intervalSeconds, 5);
});

/** What the extension hands pi when it registers, captured by a stub `pi`. */
function registeredProvider(env: string | undefined) {
	const registrations: { id: string; config: any }[] = [];
	const stub = { registerProvider: (id: string, config: unknown) => registrations.push({ id, config }) };
	const previous = process.env.LLM_POD_HAUS_URL;
	if (env === undefined) delete process.env.LLM_POD_HAUS_URL;
	else process.env.LLM_POD_HAUS_URL = env;
	try {
		registerExtension(stub as unknown as ExtensionAPI);
	} finally {
		if (previous === undefined) delete process.env.LLM_POD_HAUS_URL;
		else process.env.LLM_POD_HAUS_URL = previous;
	}
	assert.equal(registrations.length, 1);
	return registrations[0];
}

function composeModelName(): string {
	const compose = readFileSync(new URL("../../../llm/compose.yaml", import.meta.url), "utf8");
	const match = compose.match(/^\s*LLM_MODEL_NAME:\s*(\S+)\s*$/m);
	assert.ok(match, "llm/compose.yaml has an LLM_MODEL_NAME line");
	return match[1];
}

test("the registered model is the one the service serves", () => {
	const { id, config } = registeredProvider(undefined);
	assert.equal(id, "podhaus");
	assert.equal(config.api, "openai-completions");
	assert.equal(config.models.length, 1);
	assert.equal(config.models[0].id, composeModelName());
});

test("pi's reasoning levels map onto the three the chat template accepts", () => {
	const [model] = registeredProvider(undefined).config.models;
	assert.deepEqual(model.thinkingLevelMap, {
		minimal: "low",
		low: "low",
		medium: "medium",
		high: "xhigh",
		xhigh: "xhigh",
	});
});

test("the base URL is the service's /v1, or the override's", () => {
	assert.equal(registeredProvider(undefined).config.baseUrl, "https://llm.pod.haus/v1");
	assert.equal(registeredProvider("http://127.0.0.1:9").config.baseUrl, "http://127.0.0.1:9/v1");
});

test("the service signs in through Pocket ID; fractal's loopback takes the fixed key instead", () => {
	const remote = registeredProvider("https://llm.example").config as { oauth?: unknown; apiKey?: string };
	assert.equal(typeof remote.oauth, "object");
	assert.equal(remote.apiKey, undefined);
	const loopback = registeredProvider("http://127.0.0.1:8085").config as { oauth?: unknown; apiKey?: string };
	assert.equal(loopback.oauth, undefined);
	assert.equal(loopback.apiKey, "local");
});
