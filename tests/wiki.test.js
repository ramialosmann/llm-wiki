// node --test tests/ — builds a throwaway repo + wiki + registry, then drives the real bin/ commands.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

const BIN = path.join(__dirname, '..', 'bin');
const HOOKS = path.join(__dirname, '..', 'hooks');
const tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wiki-test-')));
const repo = path.join(tmp, 'repo');
const wiki = path.join(tmp, 'wiki');
const reg = path.join(tmp, 'wikis.json');
const env = { ...process.env, WIKI_REGISTRY: reg, WIKI_OFF: '', WIKI_ONLY: '' }; // a pilot WIKI_ONLY in the dev's settings must not leak in
process.env.WIKI_REGISTRY = reg;

const write = (base, files) => { for (const [f, t] of Object.entries(files)) { fs.mkdirSync(path.dirname(path.join(base, f)), { recursive: true }); fs.writeFileSync(path.join(base, f), t); } };
const git = (...a) => execFileSync('git', ['-C', repo, ...a], { encoding: 'utf8' }).trim();
const run = (cmd, args, cwd = repo, input) => spawnSync(process.execPath, [path.join(BIN, cmd), ...args], { cwd, env, encoding: 'utf8', input });

write(repo, {
  'backend/package.json': '{"dependencies":{"@nestjs/core":"1"}}',
  'backend/src/main.ts': "app.setGlobalPrefix('api');\n",
  'backend/src/users/users.controller.ts': [
    "@Controller('users')", 'export class UsersController {', "  @Get(':id')", '  @ApiOkResponse({', '    type: UserDto,', '  })',
    "  async findOne(@Param('id') id: string) {}", '', '  @Post()', '  create() {}', '}', ''].join('\n'),
  'backend/src/base/base.service.ts': 'export abstract class BaseService {}\n',
  'backend/src/index.ts': "export * from './users/users.controller';\n",
  'backend/src/jobs/cleanup.ts': "export class Cleanup {\n  @Cron('0 0 * * *')\n  async purge() {}\n}\n",
  'web/package.json': '{"dependencies":{"next":"15"}}',
  'web/app/(shop)/cart/page.tsx': 'export default function CartPage() {}\n',
  'web/app/api/orders/route.ts': 'export async function GET() {}\nexport async function POST() {}\n',
  'mobile/package.json': '{"dependencies":{"expo-router":"4"}}',
  'mobile/app/(tabs)/index.tsx': 'export default function Home() {}\n',
  'mobile/app/settings.tsx': 'export default function Settings() {}\n',
  'mobile/app/_layout.tsx': 'export default function Layout() {}\n',
});
execFileSync('git', ['init', '-q', '-b', 'main', repo]);
git('-c', 'user.email=t@t', '-c', 'user.name=t', 'add', '.');
git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'init');
const first = git('rev-parse', '--short', 'HEAD');
write(repo, { 'backend/src/users/users.controller.ts': fs.readFileSync(path.join(repo, 'backend/src/users/users.controller.ts'), 'utf8').replace('create() {}', 'create() { return 1; }') });
git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qam', 'users: create returns');

write(wiki, {
  'CLAUDE.md': '# schema\n',
  'index.md': '---\ntitle: "Index"\n---\n\n- [[user-ids]] — numeric ids, never UUIDs\n- [[cart]]: cart rules\n',
  'log.md': '---\ntitle: Log\n---\n\n# Log\n',
  'state/app.md': `---\ntitle: "State — app"\ntype: state\nsynced:\n  main: ${first}\n---\n\n**Now:** testing.\n\n**Next:**\n- more\n\n**Recent:**\n- old stuff\n`,
  'decisions/user-ids.md': '---\ntitle: "User ids"\ntype: decision\npaths: ["backend/src/users/**"]\n---\n\n> [!abstract] TL;DR\n> Users get numeric ids.\n\nNever expose UUIDs for users. See [[cart]].\n',
  'components/cart.md': '---\ntitle: "Cart"\ntype: component\nverified: app@' + first + '\n---\n\nCart lives at app:web/app/(shop)/cart/page.tsx and must survive reloads. [[user-ids]]\n',
});
fs.writeFileSync(reg, JSON.stringify({ [wiki]: { name: 'Test', repos: { app: repo } } }));

test('wiki-resolve prints the v1 KEY=value contract', () => {
  const r = run('wiki-resolve', []);
  assert.strictEqual(r.status, 0);
  assert.match(r.stdout, new RegExp(`^WIKI_ROOT='${wiki}'$`, 'm'));
  assert.match(r.stdout, /^WIKI_REPO='app'$/m);
  assert.strictEqual(run('wiki-resolve', [tmp], tmp).status, 1);
});

test('wiki-unsynced finds the commit after the synced sha', () => {
  const r = run('wiki-unsynced', []);
  assert.strictEqual(r.status, 1);
  assert.match(r.stdout, /users: create returns/);
  assert.match(r.stderr, new RegExp(`RANGE=${first}\\.\\.HEAD`));
});

test('wiki-map extracts routes, screens, jobs and exports', () => {
  const r = run('wiki-map', ['--stdout']);
  assert.strictEqual(r.status, 0);
  const m = r.stdout;
  assert.match(m, /GET \/api\/users\/:id → backend\/src\/users\/users\.controller\.ts:3 findOne/, 'multi-line decorator before method');
  assert.match(m, /POST \/api\/users → backend\/src\/users\/users\.controller\.ts:\d+ create/);
  assert.match(m, /backend\/src\/base\/base\.service\.ts: BaseService/, 'export abstract class');
  assert.doesNotMatch(m, /^- backend\/src\/index\.ts/m, 'pure barrel skipped');
  assert.match(m, /@Cron\('0 0 \* \* \*'\) → backend\/src\/jobs\/cleanup\.ts:2 purge/);
  assert.match(m, /^- \/cart → web\/app\/\(shop\)\/cart\/page\.tsx \(next page\)$/m, 'route group dropped');
  assert.match(m, /^- GET\|POST \/api\/orders → web\/app\/api\/orders\/route\.ts \(next route\)$/m);
  assert.match(m, /^- \/ → mobile\/app\/\(tabs\)\/index\.tsx \(expo screen\)$/m);
  assert.match(m, /^- \/settings → mobile\/app\/settings\.tsx \(expo screen\)$/m);
  assert.doesNotMatch(m, /_layout\.tsx \(expo/, 'layouts are not screens');
});

test('wiki-map --if-stale writes once, then no-ops at the same HEAD', () => {
  assert.strictEqual(run('wiki-map', ['--quiet']).status, 0);
  const file = path.join(wiki, 'code', 'app-map.md');
  const before = fs.statSync(file).mtimeMs;
  assert.match(fs.readFileSync(file, 'utf8'), new RegExp(`built_at: "${git('rev-parse', 'HEAD')}"`));
  assert.strictEqual(run('wiki-map', ['--if-stale', '--quiet']).status, 0);
  assert.strictEqual(fs.statSync(file).mtimeMs, before);
});

test('wiki-find ranks the owning page and the route, inside the budget', () => {
  const r = run('wiki-find', ['user', 'ids', '--budget', '300']);
  assert.strictEqual(r.status, 0);
  assert.match(r.stdout.split('\n')[1], /^decisions\/user-ids\.md — numeric ids, never UUIDs/);
  assert.match(r.stdout, /GET \/api\/users\/:id/);
  assert.ok(r.stdout.length <= 300 * 4 + 200, `over budget: ${r.stdout.length}`);
  assert.strictEqual(run('wiki-find', ['zzqqxx']).status, 1);
  assert.strictEqual(run('wiki-find', ['x'], tmp).status, 2);
});

test('session-start brief: marker first, pages, state without Recent, unsynced last, capped', () => {
  const r = spawnSync(process.execPath, [path.join(HOOKS, 'session-start.js')], { cwd: repo, env, encoding: 'utf8' });
  const c = JSON.parse(r.stdout).hookSpecificOutput.additionalContext;
  assert.ok(c.startsWith('<!-- wiki:v2 -->'));
  assert.match(c, /- decisions\/user-ids\.md — numeric ids/);
  assert.match(c, /- components\/cart\.md — cart rules/, 'colon-style index lines parse too');
  assert.match(c, /\*\*Now:\*\* testing\./);
  assert.doesNotMatch(c, /old stuff/);
  assert.match(c.trim().split('\n').pop(), /^1 unsynced commit in `app`/);
  assert.ok(c.length <= 4000);
  const off = spawnSync(process.execPath, [path.join(HOOKS, 'session-start.js')], { cwd: repo, env: { ...env, WIKI_OFF: '1' }, encoding: 'utf8' });
  assert.strictEqual(off.stdout, '');
  const only = (v) => spawnSync(process.execPath, [path.join(HOOKS, 'session-start.js')], { cwd: repo, env: { ...env, WIKI_ONLY: v }, encoding: 'utf8' }).stdout;
  assert.strictEqual(only('Other Wiki'), '', 'WIKI_ONLY excludes other wikis');
  assert.match(only('Other Wiki, Test'), /wiki:v2/, 'WIKI_ONLY includes listed wikis');
});

test('subagent-start points agents at the wiki and skips wiki-sync', () => {
  const sub = (agent) => spawnSync(process.execPath, [path.join(HOOKS, 'subagent-start.js')], { cwd: repo, env, encoding: 'utf8', input: JSON.stringify({ agent_type: agent, cwd: repo }) }).stdout;
  assert.match(JSON.parse(sub('Explore')).hookSpecificOutput.additionalContext, /wiki-find/);
  assert.strictEqual(sub('llm-wiki:wiki-sync'), '');
});

test('wiki-sync-prep maps changed files to pages and stays capped', () => {
  const r = run('wiki-sync-prep', ['--max', '5000']);
  assert.strictEqual(r.status, 0);
  assert.match(r.stdout, /- decisions\/user-ids\.md ← backend\/src\/users\/users\.controller\.ts/);
  assert.match(r.stdout, /create\(\) \{ return 1; \}/);
  assert.ok(r.stdout.length < 6000);
});

test('wiki-index --init keeps every linked page and the old body', () => {
  const r = run('wiki-index', ['--init']);
  assert.strictEqual(r.status, 0);
  const idx = fs.readFileSync(path.join(wiki, 'index.md'), 'utf8');
  for (const p of ['user-ids', 'cart', 'state/app']) assert.match(idx, new RegExp(`\\[\\[${p}\\]\\]`));
  assert.match(idx, /- \[\[user-ids\]\] — numeric ids, never UUIDs/, 'summary carried over from the old index');
  assert.match(idx, /## Previous index/);
});

test('wiki-finish bumps synced, stamps pages, appends the log without losing it', () => {
  const head = git('rev-parse', '--short', 'HEAD');
  const r = run('wiki-finish', ['sync', '--summary', 'Users create returns. Noted in the decision.', '--touched', 'user-ids', '--verified', 'cart', '--bump']);
  assert.strictEqual(r.status, 0, r.stderr);
  const state = fs.readFileSync(path.join(wiki, 'state/app.md'), 'utf8');
  assert.match(state, new RegExp(`^  main: ${head}$`, 'm'));
  assert.match(fs.readFileSync(path.join(wiki, 'components/cart.md'), 'utf8'), new RegExp(`^verified: app@${head}$`, 'm'));
  const log = fs.readFileSync(path.join(wiki, 'log.md'), 'utf8');
  assert.ok(log.startsWith('---\ntitle: Log'));
  assert.match(log, new RegExp(`## \\[\\d{4}-\\d\\d-\\d\\d\\] sync \\| app ${first}\\.\\.${head}\\n- Users create returns\\.\\n- Noted in the decision\\.\\n- Touched: \\[\\[user-ids\\]\\], \\[\\[cart\\]\\]`));
  assert.strictEqual(run('wiki-unsynced', []).status, 0, 'nothing left to sync');
});

test('wiki-lint: clean links, generated map exempt, diet flags', () => {
  const r = run('wiki-lint', [wiki, `app=${repo}`, '--diet']);
  assert.match(r.stdout, /## Broken wikilinks \(page \| target\): 0/);
  assert.doesNotMatch(r.stdout, /code\/app-map/);
  assert.match(r.stdout, /## Diet: missing summary: \(wiki-index --backfill\): \d+/);
});

test.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
