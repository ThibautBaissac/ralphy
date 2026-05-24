// CodexProvider — implements `LlmProvider` for the OpenAI Codex SDK.
//
// Phase 9 ships the provider; later phases route per-user `CODEX_HOME`
// credentials through `ProviderRunOptions.env`. The Codex SDK accepts that
// environment only on the Codex client constructor, not per-thread options.

import { Codex } from '@openai/codex-sdk';
import type { CodexOptions, ThreadEvent, Thread } from '@openai/codex-sdk';

import { mapEvent } from './mapEvent.js';
import { buildCodexThreadOptions } from './codexOptionsBuilder.js';
import { getCapabilities } from '@shared/providers/capabilities';
import type {
  ProviderCapabilities,
  ProviderRunOptions,
  ProviderRunResult,
  UnifiedMessage,
  UnifiedUserMessage,
} from '@shared/providers/types';
import type { LlmProvider, LoadTranscriptOptions } from '../types.js';

interface ActiveCodexSession {
  thread: Thread;
  abortController: AbortController;
}

const ACTIVE_SESSIONS = new Map<string, ActiveCodexSession>();
type CodexClientFactory = (options?: CodexOptions) => Codex;

const GLOBAL_CODEX_AUTH_ENV_KEYS = [
  'OPENAI_API_KEY',
  'OPENAI_BASE_URL',
  'OPENAI_ORG_ID',
  'CODEX_HOME',
  'CODEX_API_KEY',
] as const;

function compactEnvEntries(
  env: Record<string, string | undefined> | undefined,
): Record<string, string> {
  const out: Record<string, string> = {};
  if (!env) return out;
  for (const [key, value] of Object.entries(env)) {
    if (value !== undefined) out[key] = value;
  }
  return out;
}

function buildCodexProcessEnv(
  overrides: Record<string, string | undefined> | undefined,
): Record<string, string> {
  const env = compactEnvEntries(process.env);
  for (const key of GLOBAL_CODEX_AUTH_ENV_KEYS) {
    delete env[key];
  }
  return { ...env, ...compactEnvEntries(overrides) };
}

function buildSyntheticUser(
  prompt: string,
  providerSessionId: string | null,
): UnifiedUserMessage {
  return {
    type: 'user',
    id: `user_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    provider: 'openai',
    providerSessionId,
    raw: { type: 'user', content: prompt },
    content: prompt,
  };
}

async function* streamUnified(
  thread: Thread,
  prompt: string,
  signal: AbortSignal,
  resolveSessionId: (id: string) => void,
  capturePid: (pid: number | null) => void,
): AsyncGenerator<UnifiedMessage, void, unknown> {
  // 1. Synthetic user message — the Codex SDK doesn't emit the user
  //    prompt back as an event. Without this the messages table would
  //    have no user-side row for the turn.
  let providerSessionId: string | null = null;
  yield buildSyntheticUser(prompt, providerSessionId);

  // 2. The stream itself. Resolve `providerSessionId$` on the first
  //    `thread.started` event; before then, downstream messages carry
  //    a null session id (Phase 9 messageMirror buffers until the id
  //    is known — out of scope for the minimum-viable provider).
  const streamed = await thread.runStreamed(prompt, { signal });
  capturePid((streamed as unknown as { pid?: number }).pid ?? null);

  for await (const event of streamed.events) {
    const e = event as ThreadEvent;
    if (e.type === 'thread.started' && providerSessionId === null) {
      providerSessionId = e.thread_id;
      resolveSessionId(e.thread_id);
    }
    for (const unified of mapEvent(e, providerSessionId)) {
      yield unified;
    }
  }
}

export class CodexProvider implements LlmProvider {
  readonly name = 'openai' as const;

  private codex: Codex | null;
  private createCodex: CodexClientFactory;

  constructor(
    codex: Codex | null = null,
    createCodex: CodexClientFactory = (options) => new Codex(options),
  ) {
    this.codex = codex;
    this.createCodex = createCodex;
  }

  getCapabilities(): ProviderCapabilities {
    return getCapabilities('openai');
  }

  async startTurn(options: ProviderRunOptions): Promise<ProviderRunResult> {
    const threadOptions = buildCodexThreadOptions(options);
    const thread = this.getClient(options).startThread(threadOptions);
    return this.runOnThread(thread, options);
  }

  async sendTurnMessage(
    options: ProviderRunOptions & { resumeSessionId: string },
  ): Promise<ProviderRunResult> {
    const threadOptions = buildCodexThreadOptions(options);
    const thread = this.getClient(options).resumeThread(options.resumeSessionId, threadOptions);
    return this.runOnThread(thread, options);
  }

  private getClient(options: ProviderRunOptions): Codex {
    if (this.codex) return this.codex;
    return this.createCodex({ env: buildCodexProcessEnv(options.env) });
  }

  private async runOnThread(
    thread: Thread,
    options: ProviderRunOptions,
  ): Promise<ProviderRunResult> {
    const abortController = options.abortController ?? new AbortController();
    let resolveSessionId!: (id: string) => void;
    const providerSessionId$ = new Promise<string>((resolve) => {
      resolveSessionId = resolve;
    });
    providerSessionId$.then((id) => {
      ACTIVE_SESSIONS.set(id, { thread, abortController });
    });

    let pid: number | null = null;
    const capturePid = (p: number | null) => {
      pid = p;
    };

    const prompt = options.prompt ?? '';

    return {
      events: streamUnified(thread, prompt, abortController.signal, resolveSessionId, capturePid),
      providerSessionId$,
      abort: () => abortController.abort(),
      get pid() {
        return pid;
      },
    } as ProviderRunResult;
  }

  async loadTranscript(options: LoadTranscriptOptions): Promise<UnifiedMessage[]> {
    // Codex events are mirrored into the same `messages` SQLite table
    // that Anthropic uses (D4). The on-disk shape matches Claude's
    // transcript shape closely enough that the existing reader returns
    // useful rows; we adapt back to UnifiedMessage on the way out.
    const { loadAnthropicTranscript } = await import('../anthropic/sessionStore.js');
    const entries = await loadAnthropicTranscript(options);
    // Stamp the provider so downstream consumers don't see 'anthropic'
    // on rows that are actually Codex.
    return entries.map((e) => ({ ...e, provider: 'openai' }));
  }

  abortTurn(providerSessionId: string): boolean {
    const active = ACTIVE_SESSIONS.get(providerSessionId);
    if (!active) return false;
    active.abortController.abort();
    ACTIVE_SESSIONS.delete(providerSessionId);
    return true;
  }
}

export const codexProvider = new CodexProvider();
