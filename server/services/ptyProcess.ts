import { spawn as spawnChild, type ChildProcessWithoutNullStreams } from 'child_process';
import fs from 'fs';
import * as pty from 'node-pty';

export interface PtyExitEvent {
  exitCode?: number | null;
  signal?: number | string | null;
  error?: Error;
}

export interface PtyProcess {
  pid: number;
  onData(callback: (chunk: string | Buffer) => void): void;
  onExit(callback: (event: PtyExitEvent) => void): void;
  write(data: string): void;
  kill(signal?: string): void;
}

export interface PtySpawnOptions {
  name: string;
  cols: number;
  rows: number;
  env: Record<string, string>;
  cwd?: string;
}

export class PtyProcessSpawnError extends Error {
  override cause?: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'PtyProcessSpawnError';
    this.cause = cause;
  }
}

class ChildProcessPty implements PtyProcess {
  pid: number;
  private dataCallbacks: Array<(chunk: string | Buffer) => void> = [];
  private exitCallbacks: Array<(event: PtyExitEvent) => void> = [];
  private exitEvent: PtyExitEvent | null = null;

  constructor(private child: ChildProcessWithoutNullStreams) {
    this.pid = child.pid ?? 0;
    child.stdout.on('data', (chunk) => this.emitData(chunk));
    child.stderr.on('data', (chunk) => this.emitData(chunk));
    child.on('error', (error) => {
      this.emitExit({ exitCode: null, signal: null, error });
    });
    child.on('exit', (exitCode, signal) => {
      this.emitExit({ exitCode, signal });
    });
  }

  onData(callback: (chunk: string | Buffer) => void): void {
    this.dataCallbacks.push(callback);
  }

  onExit(callback: (event: PtyExitEvent) => void): void {
    if (this.exitEvent) {
      callback(this.exitEvent);
      return;
    }
    this.exitCallbacks.push(callback);
  }

  write(data: string): void {
    this.child.stdin.write(data);
  }

  kill(signal?: string): void {
    this.child.kill(signal as NodeJS.Signals | undefined);
  }

  private emitData(chunk: string | Buffer): void {
    for (const callback of this.dataCallbacks) callback(chunk);
  }

  private emitExit(event: PtyExitEvent): void {
    if (this.exitEvent) return;
    this.exitEvent = event;
    for (const callback of this.exitCallbacks) callback(event);
    this.exitCallbacks = [];
  }
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function getScriptCommand(): string | null {
  if (process.platform === 'win32') return null;
  if (process.env.RALPHY_SCRIPT_PTY_PATH) return process.env.RALPHY_SCRIPT_PTY_PATH;
  return fs.existsSync('/usr/bin/script') ? '/usr/bin/script' : 'script';
}

function buildScriptArgs(command: string, args: string[]): string[] {
  if (process.platform === 'darwin') {
    return ['-q', '/dev/null', command, ...args];
  }

  const commandLine = [command, ...args].map(shellQuote).join(' ');
  return ['-q', '-c', commandLine, '/dev/null'];
}

function spawnWithScript(
  command: string,
  args: string[],
  options: PtySpawnOptions,
): PtyProcess | null {
  const scriptCommand = getScriptCommand();
  if (!scriptCommand) return null;

  const child = spawnChild(scriptCommand, buildScriptArgs(command, args), {
    env: {
      ...options.env,
      TERM: options.name,
      COLUMNS: String(options.cols),
      LINES: String(options.rows),
    },
    stdio: ['pipe', 'pipe', 'pipe'],
    ...(options.cwd ? { cwd: options.cwd } : {}),
  });

  return new ChildProcessPty(child);
}

export function spawnPtyProcess(
  command: string,
  args: string[],
  options: PtySpawnOptions,
): PtyProcess {
  try {
    return pty.spawn(command, args, options);
  } catch (error) {
    const fallback = spawnWithScript(command, args, options);
    if (fallback) return fallback;
    throw new PtyProcessSpawnError(
      `Failed to start ${command} in a pseudo-terminal`,
      error,
    );
  }
}
