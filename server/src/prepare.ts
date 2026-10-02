/**
 * The bridge to the Python rules.
 *
 * This server does not know what a valid map is, where one belongs, or how a
 * map's identity is computed - and that is deliberate. Those rules live in
 * `awrbc.core`, are covered by its tests, and are re-run by the library's CI.
 * Reimplementing them here would mean two answers to the same question, and
 * the most important of them is a content hash: a hash that drifted would not
 * throw, it would quietly stop de-duplicating and the archive would fill with
 * copies of one map.
 *
 * So: spawn `awrbc prepare`, give it the upload, read JSON back. A process per
 * submission is a real cost and an irrelevant one at this volume.
 */
import { spawn } from 'node:child_process';

/** What `awrbc prepare` says when it will not take a submission. */
export interface Rejection {
  ok: false;
  code: string;
  error: string;
  findings: Array<{ code: string; severity: string; message: string }>;
}

/** What it says when it will: everything needed to open the pull request. */
export interface Prepared {
  ok: true;
  kind: string;
  path: string;
  folder: string;
  version: number;
  branch: string;
  title: string;
  body: string;
  /** Repo path to base64 content. Base64 because a preview is binary. */
  files: Record<string, string>;
  warnings: Array<{ code: string; severity: string; message: string }>;
  hasPreview: boolean;
}

export type Outcome = Prepared | Rejection;

/** The command itself failed, as opposed to refusing a submission. */
export class PrepareFailed extends Error {
  constructor(message: string, readonly detail = '') {
    super(message);
    this.name = 'PrepareFailed';
  }
}

export interface Options {
  /**
   * How to run the tool. Default `awrbc`.
   *
   * May carry arguments - `python -m awrbc` is a perfectly normal way to have
   * it in a container, where the console script need not be on PATH, and an
   * absolute path into a venv is another. Split on spaces, which is enough for
   * every real form and avoids inviting a shell.
   */
  command?: string;
  /** Where to read the archive index from, if not the public one. */
  catalog?: string;
  base?: string;
  /** Milliseconds before the child is killed. */
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT = 30_000;

export async function prepare(
  upload: Buffer,
  author: { id: string; username: string },
  update: string | undefined,
  options: Options = {},
): Promise<Outcome> {
  const argv = ['prepare', '-', '--author-id', author.id,
                '--author-name', author.username];
  if (update) argv.push('--update', update);
  if (options.catalog) argv.push('--catalog', options.catalog);
  else if (options.base) argv.push('--base', options.base);

  const [exe, ...prefix] = (options.command ?? 'awrbc').split(/\s+/);
  // No shell: argv goes straight to the process, so nothing a submitter
  // controls can ever be interpreted as a command.
  const child = spawn(exe!, [...prefix, ...argv], {
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  child.stdout.on('data', (d: Buffer) => stdout.push(d));
  child.stderr.on('data', (d: Buffer) => stderr.push(d));

  // The upload goes in on stdin rather than a temp file: nothing to clean up,
  // and no path on disk for anything else to find.
  child.stdin.end(upload);

  const timeout = options.timeoutMs ?? DEFAULT_TIMEOUT;
  const timer = setTimeout(() => child.kill('SIGKILL'), timeout);

  const code: number | null = await new Promise((resolve, reject) => {
    child.on('error', reject);
    child.on('close', resolve);
  }).finally(() => clearTimeout(timer)) as number | null;

  const err = Buffer.concat(stderr).toString('utf8').trim();
  if (code !== 0) {
    throw new PrepareFailed(
      code === null ? 'the validator was killed (timed out?)'
                    : `the validator exited ${code}`, err);
  }

  const text = Buffer.concat(stdout).toString('utf8');
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new PrepareFailed('the validator did not return JSON',
                            err || text.slice(0, 400));
  }
  if (typeof parsed !== 'object' || parsed === null || !('ok' in parsed)) {
    throw new PrepareFailed('the validator returned something unexpected',
                            text.slice(0, 400));
  }
  return parsed as Outcome;
}

/** Decode what `prepare` returned into the bytes to commit. */
export function filesToCommit(prepared: Prepared): Record<string, Buffer> {
  const out: Record<string, Buffer> = {};
  for (const [path, b64] of Object.entries(prepared.files)) {
    out[path] = Buffer.from(b64, 'base64');
  }
  return out;
}

/** Is the tool present and runnable? Called at startup so a bad deploy says
 *  so immediately rather than at somebody's first upload. */
export async function available(command = 'awrbc'): Promise<string | null> {
  const [exe, ...prefix] = command.split(/\s+/);
  return new Promise((resolve) => {
    const child = spawn(exe!, [...prefix, '--help'], { stdio: 'ignore' });
    child.on('error', (e) => resolve(e.message));
    child.on('close', (code) =>
      resolve(code === 0 ? null : `${command} --help exited ${code}`));
  });
}
