/**
 * Provider for the local model service at llm.pod.haus.
 *
 * Signs in through Pocket ID's device flow: /login shows one link with the code
 * already in it, which can be approved on any device, and pi renews the token
 * through the refresh token afterwards. Mirrors llm/client/llm_token.py in the
 * podhaus repository, which does the same sign-in for Claude Code.
 *
 * Usage:
 *   pi -e ./llm-pod-haus.ts
 *   # then /login llm-pod-haus
 *
 * Only types are imported from pi, so the file also runs under plain node.
 */

import type { OAuthCredentials, OAuthLoginCallbacks } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const ISSUER = "https://id.pod.haus";
// The public Pocket ID client declared in podhaus's terraform/pocket_id.tf.
const CLIENT_ID = "llm-token";
// email and groups put the person's address and group names in what Pocket ID's
// userinfo endpoint returns for this token, which is what Pomerium reads.
const SCOPE = "openid email groups";
const DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code";
const DEFAULT_SERVICE_URL = "https://llm.pod.haus";
const PROVIDER_ID = "llm-pod-haus";
// pi has no token cache of its own to outlive, so a few minutes of margin is
// enough to refresh before a request goes out with an expired token.
const REFRESH_BEFORE_EXPIRY_MS = 5 * 60 * 1000;
// RFC 8628: each slow_down answer adds five seconds to the polling interval.
const SLOW_DOWN_STEP_SECONDS = 5;
// RFC 8628: a reply without an interval means polling every five seconds.
const DEFAULT_INTERVAL_SECONDS = 5;
const HTTP_TIMEOUT_MS = 30_000;

export interface Clock {
	now(): number;
	sleep(ms: number, signal: AbortSignal | undefined): Promise<void>;
}

export const systemClock: Clock = {
	now: () => Date.now(),
	sleep(ms, signal) {
		return new Promise((resolve, reject) => {
			if (signal?.aborted) return reject(abortError());
			const timer = setTimeout(() => {
				signal?.removeEventListener("abort", onAbort);
				resolve();
			}, ms);
			const onAbort = () => {
				clearTimeout(timer);
				reject(abortError());
			};
			signal?.addEventListener("abort", onAbort, { once: true });
		});
	},
};

function abortError(): Error {
	return new Error("Sign-in cancelled");
}

interface DeviceSignIn {
	deviceCode: string;
	link: string;
	userCode: string;
	intervalSeconds: number;
	expiresInSeconds: number;
	expiresAt: number;
}

interface Reply {
	ok: boolean;
	body: Record<string, unknown>;
}

/** Pocket ID's device sign-in and refresh grants, for one public client. */
export class PocketId {
	private readonly issuer: string;
	private readonly clientId: string;
	private readonly clock: Clock;
	private endpoints: { deviceAuthorization: string; token: string } | undefined;

	constructor(issuer: string, clientId: string, clock: Clock) {
		this.issuer = issuer;
		this.clientId = clientId;
		this.clock = clock;
	}

	async login(callbacks: OAuthLoginCallbacks): Promise<OAuthCredentials> {
		const signal = callbacks.signal;
		const signIn = await this.startSignIn(signal);
		callbacks.onDeviceCode({
			userCode: signIn.userCode,
			verificationUri: signIn.link,
			intervalSeconds: signIn.intervalSeconds,
			expiresInSeconds: signIn.expiresInSeconds,
		});
		callbacks.onProgress?.("Waiting for the sign-in to be approved");
		const credentials = await this.finishSignIn(signIn, signal);
		callbacks.onProgress?.("Signed in");
		return credentials;
	}

	async refresh(credentials: OAuthCredentials, signal: AbortSignal): Promise<OAuthCredentials> {
		const reply = await this.post(
			(await this.discover(signal)).token,
			{ grant_type: "refresh_token", refresh_token: credentials.refresh, client_id: this.clientId },
			signal,
		);
		if (!reply.ok) {
			throw new Error(`Pocket ID no longer accepts the saved sign-in (${reply.body.error}). Run /login ${PROVIDER_ID}`);
		}
		return this.credentialsFrom(reply.body);
	}

	private async startSignIn(signal: AbortSignal | undefined): Promise<DeviceSignIn> {
		const reply = await this.post(
			(await this.discover(signal)).deviceAuthorization,
			{ client_id: this.clientId, scope: SCOPE },
			signal,
		);
		if (!reply.ok) throw new Error(`Pocket ID refused to start the sign-in (${reply.body.error})`);
		const body = reply.body;
		const expiresInSeconds = requiredField(body, "expires_in", "number");
		return {
			deviceCode: requiredField(body, "device_code", "string"),
			link: requiredField(body, "verification_uri_complete", "string"),
			userCode: requiredField(body, "user_code", "string"),
			intervalSeconds: body.interval === undefined ? DEFAULT_INTERVAL_SECONDS : requiredField(body, "interval", "number"),
			expiresInSeconds,
			expiresAt: this.clock.now() + expiresInSeconds * 1000,
		};
	}

	/** Waits until the link is approved, polling as RFC 8628 prescribes. */
	private async finishSignIn(signIn: DeviceSignIn, signal: AbortSignal | undefined): Promise<OAuthCredentials> {
		const tokenEndpoint = (await this.discover(signal)).token;
		let interval = signIn.intervalSeconds;
		for (;;) {
			await this.clock.sleep(interval * 1000, signal);
			if (this.clock.now() >= signIn.expiresAt) throw new Error("The sign-in link expired before it was approved");
			const reply = await this.post(
				tokenEndpoint,
				{ grant_type: DEVICE_CODE_GRANT, device_code: signIn.deviceCode, client_id: this.clientId },
				signal,
			);
			if (reply.ok) return this.credentialsFrom(reply.body);
			switch (reply.body.error) {
				case "authorization_pending":
					break;
				case "slow_down":
					interval += SLOW_DOWN_STEP_SECONDS;
					break;
				case "access_denied":
					throw new Error("The sign-in was denied");
				case "expired_token":
					throw new Error("The sign-in link expired before it was approved");
				default:
					throw new Error(`Sign-in failed (${reply.body.error})`);
			}
		}
	}

	private credentialsFrom(body: Record<string, unknown>): OAuthCredentials {
		return {
			access: requiredField(body, "access_token", "string"),
			refresh: requiredField(body, "refresh_token", "string"),
			expires: this.clock.now() + requiredField(body, "expires_in", "number") * 1000 - REFRESH_BEFORE_EXPIRY_MS,
		};
	}

	private async discover(signal: AbortSignal | undefined): Promise<{ deviceAuthorization: string; token: string }> {
		if (this.endpoints === undefined) {
			const response = await fetch(`${this.issuer}/.well-known/openid-configuration`, {
				signal: withTimeout(signal),
			});
			if (!response.ok) throw new Error(`Pocket ID discovery answered ${response.status}`);
			const document = (await response.json()) as Record<string, string>;
			this.endpoints = {
				deviceAuthorization: document.device_authorization_endpoint,
				token: document.token_endpoint,
			};
		}
		return this.endpoints;
	}

	/** Pocket ID's answer, refusals included. A server error is raised: Pocket ID
	 * failing is not a reason to ask the person to sign in again. */
	private async post(url: string, form: Record<string, string>, signal: AbortSignal | undefined): Promise<Reply> {
		const response = await fetch(url, {
			method: "POST",
			headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
			body: new URLSearchParams(form),
			signal: withTimeout(signal),
		});
		if (response.status >= 500) throw new Error(`Pocket ID answered ${response.status}`);
		return { ok: response.ok, body: (await response.json()) as Record<string, unknown> };
	}
}

/** A field Pocket ID must send: a reply without it fails here, by name, rather
 * than surfacing later as an undefined token or a NaN polling interval. */
function requiredField<K extends "string" | "number">(
	body: Record<string, unknown>,
	name: string,
	kind: K,
): K extends "string" ? string : number {
	const value = body[name];
	if (value === undefined) throw new Error(`Pocket ID's reply is missing ${name}`);
	if (typeof value !== kind) throw new Error(`Pocket ID's reply has an invalid ${name}: expected a ${kind}`);
	return value as K extends "string" ? string : number;
}

function withTimeout(signal: AbortSignal | undefined): AbortSignal {
	const timeout = AbortSignal.timeout(HTTP_TIMEOUT_MS);
	return signal === undefined ? timeout : AbortSignal.any([signal, timeout]);
}

export default function (pi: ExtensionAPI) {
	const pocketId = new PocketId(ISSUER, CLIENT_ID, systemClock);
	const serviceUrl = process.env.LLM_POD_HAUS_URL ?? DEFAULT_SERVICE_URL;

	pi.registerProvider(PROVIDER_ID, {
		baseUrl: `${serviceUrl}/v1`,
		api: "openai-completions",
		models: [
			{
				id: "qwen3.8-27b",
				name: "Qwen3.8 27B (pod.haus)",
				reasoning: true,
				// llama.cpp passes reasoning_effort straight into the chat template, which
				// accepts only low, medium and xhigh and answers HTTP 500 to anything else,
				// while pi sends its own level names. xhigh is mapped, so pi offers it, but
				// it measured much slower than medium and stays the person's explicit
				// choice; high maps to it because the template has no level between.
				thinkingLevelMap: { minimal: "low", low: "low", medium: "medium", high: "xhigh", xhigh: "xhigh" },
				input: ["text"],
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				contextWindow: 150000,
				maxTokens: 32768,
			},
		],
		oauth: {
			name: "pod.haus local model",
			login: (callbacks) => pocketId.login(callbacks),
			refreshToken: (credentials, signal) => pocketId.refresh(credentials, signal),
			getApiKey: (credentials) => credentials.access,
		},
	});
}
