/**
 * The first durable state this project has.
 *
 * Everything else the endpoint knows is derived: map content lives in git, and
 * a pull request's fate is GitHub's to say. What is *only* here is the join
 * between a Discord account and the submissions it made - which cannot live in
 * the archive, because git history is permanent and world-readable and a
 * Discord id published once cannot be unpublished (decision #44).
 *
 * ## What this is not
 *
 * **Not a second source of truth for map content** (decision #49). No terrain,
 * no units, no authorship. A content hash is stored, but as a key, not as the
 * map.
 *
 * **Not the authority on whether a submission was accepted.** GitHub owns
 * that. A `status` column here would be a copy that drifts until the two
 * disagree about reality, and the one people believe would be the wrong one.
 * So pull request state lives in a table named `pr_state_cache`, refreshed
 * from GitHub and carrying the time it was read. The name is the comment: if
 * it is ever treated as truth, that is a bug with a label on it.
 *
 * ## Why SQLite
 *
 * One host, a handful of writes a day, and a file that moves to another
 * machine by being copied. What would rule it out is more than one instance of
 * this server, or a platform with a disposable filesystem; neither is where
 * this runs. Postgres would buy concurrency that does not exist here and cost
 * a service to run, back up and major-version upgrade.
 *
 * ## Why every method is async
 *
 * `node:sqlite` answers synchronously. These return promises anyway so that
 * the routes never learn which database they are talking to, and moving to
 * Postgres is this file plus a connection string rather than every call site
 * and every function above it. That reversibility is most of the reason
 * SQLite is defensible at all.
 *
 * `node:sqlite` is still flagged experimental by Node, which is a real risk
 * for the one store that cannot be rebuilt from anything else. It is taken
 * because the surface used here is tiny and the isolation above means swapping
 * to `better-sqlite3` is one file - not because the warning is not meant.
 */
import { DatabaseSync } from 'node:sqlite';

/** One submission, as this endpoint recorded it at the time. */
export interface Submission {
  discordId: string;
  username: string;
  mapName: string;
  folder: string;
  version: number;
  contentHash: string;
  branch: string;
  prNumber: number;
  prUrl: string;
  createdAt: string;
}

/** What GitHub last said about a pull request, and when it said it. */
export interface PrState {
  prNumber: number;
  state: 'open' | 'merged' | 'closed';
  checkedAt: string;
}

/**
 * Schema, in order. Append only - never edit one that has shipped.
 *
 * A migration that has run on a live database is history; changing it means
 * two machines disagree about what version 3 was, and nothing will say so.
 */
const MIGRATIONS: string[] = [
  `CREATE TABLE submissions (
     id            INTEGER PRIMARY KEY,
     discord_id    TEXT    NOT NULL,
     username      TEXT    NOT NULL,
     map_name      TEXT    NOT NULL,
     folder        TEXT    NOT NULL,
     version       INTEGER NOT NULL,
     content_hash  TEXT    NOT NULL,
     branch        TEXT    NOT NULL,
     pr_number     INTEGER NOT NULL,
     pr_url        TEXT    NOT NULL,
     -- ISO 8601 UTC, as text. Portable to Postgres, readable in a shell, and
     -- sortable as a string, which is what the indexes below rely on.
     created_at    TEXT    NOT NULL
   );
   CREATE UNIQUE INDEX submissions_by_pr ON submissions(pr_number);
   CREATE INDEX submissions_by_user ON submissions(discord_id, created_at);
   CREATE INDEX submissions_by_hash ON submissions(content_hash);`,

  `CREATE TABLE pr_state_cache (
     pr_number  INTEGER PRIMARY KEY,
     state      TEXT NOT NULL,
     checked_at TEXT NOT NULL
   );`,
];

const nowIso = () => new Date().toISOString();

export class Store {
  private constructor(private readonly db: DatabaseSync) {}

  /**
   * Open a database, applying any migrations it has not seen.
   *
   * `:memory:` is a real path to SQLite and is what the tests use, so nothing
   * here special-cases it.
   */
  static async open(path: string): Promise<Store> {
    const db = new DatabaseSync(path);
    // Readers do not block the writer. Without this a single slow read can
    // make a submission wait, which is a strange way to lose an upload.
    // Ignored for :memory:, where there is nothing to journal.
    if (path !== ':memory:') db.exec('PRAGMA journal_mode = WAL');
    // SQLite does not enforce foreign keys unless asked, per connection.
    db.exec('PRAGMA foreign_keys = ON');
    db.exec('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)');

    const row = db.prepare('SELECT max(version) AS v FROM schema_version')
                  .get() as { v: number | null };
    const at = row?.v ?? 0;
    for (let i = at; i < MIGRATIONS.length; i++) {
      db.exec('BEGIN');
      try {
        db.exec(MIGRATIONS[i]!);
        db.prepare('INSERT INTO schema_version (version) VALUES (?)').run(i + 1);
        db.exec('COMMIT');
      } catch (e) {
        db.exec('ROLLBACK');
        throw new Error(`migration ${i + 1} failed: ${(e as Error).message}`);
      }
    }
    return new Store(db);
  }

  /** How many migrations this database has had, for /health and for tests. */
  async version(): Promise<number> {
    const row = this.db.prepare('SELECT max(version) AS v FROM schema_version')
                       .get() as { v: number | null };
    return row?.v ?? 0;
  }

  /**
   * Record a submission that actually opened a pull request.
   *
   * Keyed on the pull request number, so replaying the same one is not an
   * error and does not duplicate a row - the endpoint should be able to retry
   * a write without inventing a second submission.
   */
  async recordSubmission(s: Submission): Promise<void> {
    this.db.prepare(
      `INSERT INTO submissions
         (discord_id, username, map_name, folder, version,
          content_hash, branch, pr_number, pr_url, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(pr_number) DO UPDATE SET
         map_name = excluded.map_name,
         folder   = excluded.folder,
         version  = excluded.version,
         pr_url   = excluded.pr_url`,
    ).run(s.discordId, s.username, s.mapName, s.folder, s.version,
          s.contentHash, s.branch, s.prNumber, s.prUrl,
          s.createdAt || nowIso());
  }

  /** One person's submissions, newest first. */
  async submissionsFor(discordId: string, limit = 50): Promise<Submission[]> {
    const rows = this.db.prepare(
      `SELECT * FROM submissions WHERE discord_id = ?
       ORDER BY created_at DESC, id DESC LIMIT ?`,
    ).all(discordId, limit) as Record<string, unknown>[];
    return rows.map(toSubmission);
  }

  /**
   * When this account's recent submissions happened, newest first.
   *
   * The rate limiter asks this rather than keeping its own counters: the
   * submissions *are* the record, and a second table counting them could
   * disagree with the first.
   */
  async submissionTimesSince(discordId: string, sinceIso: string):
      Promise<string[]> {
    const rows = this.db.prepare(
      `SELECT created_at FROM submissions
       WHERE discord_id = ? AND created_at >= ?
       ORDER BY created_at DESC`,
    ).all(discordId, sinceIso) as { created_at: string }[];
    return rows.map((r) => r.created_at);
  }

  /** Any submission of this exact map content, by anyone. For telling "you
   *  already sent this" from "a different map with the same name" - see
   *  decision #58, which this is groundwork for rather than a fix of. */
  async findByHash(contentHash: string): Promise<Submission | null> {
    const row = this.db.prepare(
      'SELECT * FROM submissions WHERE content_hash = ? ORDER BY id DESC LIMIT 1',
    ).get(contentHash) as Record<string, unknown> | undefined;
    return row ? toSubmission(row) : null;
  }

  /** Remember what GitHub said. Not what is true - what it said, and when. */
  async cachePrStates(states: PrState[]): Promise<void> {
    const stmt = this.db.prepare(
      `INSERT INTO pr_state_cache (pr_number, state, checked_at)
       VALUES (?, ?, ?)
       ON CONFLICT(pr_number) DO UPDATE SET
         state = excluded.state, checked_at = excluded.checked_at`,
    );
    this.db.exec('BEGIN');
    try {
      for (const s of states) stmt.run(s.prNumber, s.state, s.checkedAt);
      this.db.exec('COMMIT');
    } catch (e) {
      this.db.exec('ROLLBACK');
      throw e;
    }
  }

  /** The last known state of each pull request asked about. Absent means
   *  never checked, which is different from "open" and is left to the caller
   *  to say so. */
  async cachedPrStates(prNumbers: number[]): Promise<Map<number, PrState>> {
    const out = new Map<number, PrState>();
    if (!prNumbers.length) return out;
    const holes = prNumbers.map(() => '?').join(',');
    const rows = this.db.prepare(
      `SELECT * FROM pr_state_cache WHERE pr_number IN (${holes})`,
    ).all(...prNumbers) as Record<string, unknown>[];
    for (const r of rows) {
      out.set(Number(r['pr_number']), {
        prNumber: Number(r['pr_number']),
        state: String(r['state']) as PrState['state'],
        checkedAt: String(r['checked_at']),
      });
    }
    return out;
  }

  async close(): Promise<void> {
    this.db.close();
  }
}

function toSubmission(r: Record<string, unknown>): Submission {
  return {
    discordId: String(r['discord_id']),
    username: String(r['username']),
    mapName: String(r['map_name']),
    folder: String(r['folder']),
    version: Number(r['version']),
    contentHash: String(r['content_hash']),
    branch: String(r['branch']),
    prNumber: Number(r['pr_number']),
    prUrl: String(r['pr_url']),
    createdAt: String(r['created_at']),
  };
}
