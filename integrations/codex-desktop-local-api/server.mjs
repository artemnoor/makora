import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { watch } from 'node:fs';
import { readdir } from 'node:fs/promises';
import { createConnection } from 'node:net';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';

const root = dirname(fileURLToPath(import.meta.url));
const shell = process.env.CODEX_POWERSHELL_PATH || 'pwsh';
const cwd = process.env.CODEX_DEFAULT_CWD || process.cwd();
const codex = spawn(process.env.CODEX_APP_SERVER_BINARY || shell, process.env.CODEX_APP_SERVER_BINARY ? ['app-server', '--listen', 'stdio://'] : ['-NoLogo', '-NoProfile', '-File', join(root, 'appserver-uds.ps1')], {
  cwd,
  env: process.env,
  stdio: ['pipe', 'pipe', 'pipe'],
  windowsHide: true,
});

let nextId = 1;
let stdoutBuffer = '';
let ready = false;
let appServerVersion = 'starting';
const pending = new Map();
const subscribers = new Set();
const recentEvents = [];
let eventSequence = 0;
const eventEpoch = randomUUID();
const operations = new Map();
const activeThreadOperations = new Map();
const threadSendInFlight = new Set();
const approvals = new Map();
const startedThreads = new Set();
const resumedThreads = new Set();
const appToolsContextThreadId = process.env.CODEX_APP_TOOLS_CONTEXT_THREAD_ID || '';
const appToolsContextHostId = process.env.CODEX_APP_TOOLS_CONTEXT_HOST_ID || 'local';
let appToolsSocket = null;
let appToolsConnectPromise = null;
let appToolsBuffer = Buffer.alloc(0);
let appToolsRequestId = 1;
const appToolsPending = new Map();
let localStoreWatchSupported = false;
let localStoreWatcher = null;
let localStoreEventTimer = null;

function failAppToolsSocket(error, socket = appToolsSocket) {
  // A close event from an old connection must not tear down its replacement.
  if (socket !== appToolsSocket) return;
  appToolsSocket = null;
  appToolsConnectPromise = null;
  appToolsBuffer = Buffer.alloc(0);
  for (const request of appToolsPending.values()) {
    clearTimeout(request.timer);
    request.reject(error);
  }
  appToolsPending.clear();
}

function handleAppToolsData(socket, chunk) {
  if (socket !== appToolsSocket) return;
  appToolsBuffer = Buffer.concat([appToolsBuffer, chunk]);
  while (appToolsBuffer.length >= 4) {
    const size = appToolsBuffer.readUInt32LE(0);
    if (size > 8 * 1024 * 1024) return socket.destroy(new Error('Codex app-tools frame exceeds 8 MiB'));
    if (appToolsBuffer.length < size + 4) return;
    const raw = appToolsBuffer.subarray(4, size + 4).toString('utf8');
    appToolsBuffer = appToolsBuffer.subarray(size + 4);
    let message;
    try { message = JSON.parse(raw); }
    catch { return socket.destroy(new Error('Codex app-tools returned invalid JSON')); }
    const request = appToolsPending.get(Number(message.id));
    if (!request) continue;
    appToolsPending.delete(Number(message.id));
    clearTimeout(request.timer);
    if (message.error) request.reject(new Error(message.error.message || 'Codex app-tools request failed'));
    else request.resolve(message.result);
  }
}

async function connectAppTools() {
  if (appToolsSocket && !appToolsSocket.destroyed) return appToolsSocket;
  if (appToolsConnectPromise) return appToolsConnectPromise;
  appToolsConnectPromise = (async () => {
    const names = await readdir('\\\\.\\pipe\\');
    const configured = process.env.CODEX_APP_TOOLS_PIPE_NAME;
    const pipes = names.filter(name => /^codex-app-tools-[\w-]+$/.test(name));
    const pipeName = configured && pipes.includes(configured) ? configured : pipes.length === 1 ? pipes[0] : null;
    if (!pipeName) throw new Error(pipes.length ? 'Несколько Desktop app-tools pipe; задайте CODEX_APP_TOOLS_PIPE_NAME' : 'Codex Desktop app-tools pipe не найден');
    const socket = createConnection(`\\\\.\\pipe\\${pipeName}`);
    await new Promise((resolve, reject) => {
      const onError = error => { socket.destroy(); reject(error); };
      socket.once('error', onError);
      socket.once('connect', () => { socket.off('error', onError); resolve(); });
    });
    appToolsSocket = socket;
    appToolsBuffer = Buffer.alloc(0);
    socket.on('data', chunk => handleAppToolsData(socket, chunk));
    socket.on('error', error => failAppToolsSocket(error, socket));
    socket.on('close', () => failAppToolsSocket(new Error('Codex Desktop app-tools pipe closed'), socket));
    return socket;
  })().finally(() => { appToolsConnectPromise = null; });
  return appToolsConnectPromise;
}

async function appToolsRpc(method, params = {}) {
  const socket = await connectAppTools();
  const id = appToolsRequestId++;
  const payload = Buffer.from(JSON.stringify({ id, jsonrpc: '2.0', method, params }), 'utf8');
  if (payload.length > 8 * 1024 * 1024) throw new Error('Codex app-tools request exceeds 8 MiB');
  const frame = Buffer.allocUnsafe(payload.length + 4);
  frame.writeUInt32LE(payload.length, 0);
  payload.copy(frame, 4);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      const error = new Error(`${method} timed out`);
      appToolsPending.delete(id);
      reject(error);
      // Never cancel unrelated requests because one call timed out. Reconnect
      // only after the connection has no other requests in flight.
      if (socket === appToolsSocket && appToolsPending.size === 0) {
        failAppToolsSocket(error, socket);
        socket.destroy();
      }
    }, 15000);
    appToolsPending.set(id, { resolve, reject, timer });
    socket.write(frame, error => {
      if (!error) return;
      appToolsPending.delete(id);
      clearTimeout(timer);
      reject(error);
    });
  });
}

function appToolsText(result) {
  const text = (result?.contentItems || []).filter(item => item.type === 'inputText').map(item => item.text).join('\n');
  if (!result?.success) throw new Error(text || 'Codex Desktop app-tools rejected the request');
  return text;
}

function parseAppToolsJson(result) {
  const text = appToolsText(result);
  try { return JSON.parse(text); }
  catch { throw new Error('Codex Desktop app-tools returned an unexpected response'); }
}

async function callDesktopTool(tool, args = {}) {
  if (!appToolsContextThreadId) throw new Error('Не задан CODEX_APP_TOOLS_CONTEXT_THREAD_ID для Desktop bridge');
  const turnId = await latestThreadTurnId(appToolsContextThreadId);
  if (!turnId) throw new Error('Не удалось получить актуальный turnId bridge-контекста');
  return appToolsRpc('tools/call', {
    arguments: args,
    callerSource: 'codex',
    callId: randomUUID(),
    hostId: appToolsContextHostId,
    namespace: 'codex_app',
    threadId: appToolsContextThreadId,
    tool,
    turnId,
  });
}

let desktopThreadsInFlight = null;
let desktopThreadsCache = null;
let desktopThreadsCachedAt = 0;
let desktopThreadsAttemptedAt = 0;
async function listDesktopThreads() {
  if (desktopThreadsCache) {
    if (Date.now() - desktopThreadsCachedAt >= 3000 && Date.now() - desktopThreadsAttemptedAt >= 5000) {
      // Keep the last successful snapshot visible while Desktop responds.
      refreshDesktopThreads().catch(() => {});
    }
    return desktopThreadsCache;
  }
  return refreshDesktopThreads();
}

function refreshDesktopThreads() {
  if (desktopThreadsInFlight) return desktopThreadsInFlight;
  desktopThreadsAttemptedAt = Date.now();
  desktopThreadsInFlight = fetchDesktopThreads().then(rows => {
    desktopThreadsCache = rows;
    desktopThreadsCachedAt = Date.now();
    return rows;
  }).finally(() => { desktopThreadsInFlight = null; });
  return desktopThreadsInFlight;
}

async function fetchDesktopThreads() {
  const result = await callDesktopTool('list_threads', { limit: 50 });
  const data = parseAppToolsJson(result);
  const seen = new Set();
  const rows = [...(data.pinnedThreads || []), ...(data.threads || [])]
    .filter(thread => thread.kind === 'codex' && thread.id && !seen.has(thread.id) && seen.add(thread.id));
  return rows
    .map(thread => ({
      id: thread.id,
      title: thread.title || 'Новый чат',
      preview: thread.summary || thread.preview || '',
      cwd: thread.cwd || '',
      updatedAt: typeof thread.updatedAt === 'number' ? thread.updatedAt : Math.floor(new Date(thread.updatedAt || 0).getTime() / 1000) || 0,
      status: thread.status,
      projectId: thread.projectId || null,
      hostId: thread.hostId || appToolsContextHostId,
      source: thread.kind,
      desktopAppTools: true,
    }));
}

function openDesktopHistoryIndex() {
  if (!process.env.CODEX_HOME) throw new Error('CODEX_HOME is not configured');
  const database = new DatabaseSync(join(process.env.CODEX_HOME, 'state_5.sqlite'), { readOnly: true });
  database.exec('PRAGMA query_only=ON');
  const columns = new Set(database.prepare('PRAGMA table_info(threads)').all().map(row => row.name));
  for (const column of ['id', 'name', 'title', 'preview', 'cwd', 'updated_at', 'updated_at_ms', 'model', 'project_id', 'archived', 'thread_source', 'originator']) {
    if (!columns.has(column)) {
      database.close();
      throw new Error(`Codex history index does not contain ${column}`);
    }
  }
  return database;
}

function isIndexedDesktopThread(threadId) {
  const database = openDesktopHistoryIndex();
  try {
    return Boolean(database.prepare(`
      SELECT 1 FROM threads
      WHERE id = ? AND originator = 'Codex Desktop' AND archived = 0 AND thread_source = 'user'
      LIMIT 1
    `).get(threadId));
  } finally { database.close(); }
}

function listIndexedDesktopThreads(url) {
  const database = openDesktopHistoryIndex();
  try {
    const requestedLimit = Number(url.searchParams.get('limit') || 30);
    if (!Number.isInteger(requestedLimit) || requestedLimit < 1) throw Object.assign(new Error('Invalid limit'), { status: 400 });
    const limit = Math.min(50, requestedLimit);
    let cursor = null;
    const token = url.searchParams.get('cursor');
    if (token) {
      try { cursor = JSON.parse(Buffer.from(token, 'base64url').toString('utf8')); }
      catch { throw Object.assign(new Error('Invalid Desktop history cursor'), { status: 400 }); }
      if (!Number.isFinite(cursor.updatedAtMs) || typeof cursor.id !== 'string') {
        throw Object.assign(new Error('Invalid Desktop history cursor'), { status: 400 });
      }
    }
    const orderTime = 'COALESCE(updated_at_ms, CAST(updated_at * 1000 AS INTEGER))';
    const cursorFilter = cursor ? `AND (${orderTime} < ? OR (${orderTime} = ? AND id < ?))` : '';
    const values = cursor ? [cursor.updatedAtMs, cursor.updatedAtMs, cursor.id, limit + 1] : [limit + 1];
    const rows = database.prepare(`
      SELECT id, name, title, preview, cwd, updated_at, updated_at_ms, model, project_id
      FROM threads
      WHERE originator = 'Codex Desktop' AND archived = 0 AND thread_source = 'user'
      ${cursorFilter}
      ORDER BY ${orderTime} DESC, id DESC
      LIMIT ?
    `).all(...values);
    const hasMore = rows.length > limit;
    const pageRows = rows.slice(0, limit);
    const threads = pageRows.map(thread => ({
      id: thread.id,
      title: thread.name || thread.title || thread.preview?.split(/\r?\n/)[0]?.slice(0, 120) || 'Новый чат',
      preview: thread.preview || '',
      cwd: thread.cwd || '',
      updatedAt: Number.isFinite(thread.updated_at_ms)
        ? Math.floor(thread.updated_at_ms / 1000)
        : Math.floor(Number(thread.updated_at) || 0),
      model: thread.model || '',
      projectId: thread.project_id || null,
      hostId: appToolsContextHostId,
      source: 'desktopHistoryIndex',
      desktopHistory: true,
    }));
    const last = pageRows.at(-1);
    const lastUpdatedAtMs = last && (Number.isFinite(last.updated_at_ms)
      ? last.updated_at_ms
      : Math.floor((Number(last.updated_at) || 0) * 1000));
    const nextCursor = hasMore && last
      ? Buffer.from(JSON.stringify({ updatedAtMs: lastUpdatedAtMs, id: last.id })).toString('base64url')
      : null;
    return { threads, nextCursor, source: 'readonly-desktop-state-index' };
  } finally { database.close(); }
}

async function listDesktopProjects() {
  const result = await callDesktopTool('list_projects');
  return (parseAppToolsJson(result).projects || []).map(project => ({
    ...project,
    id: project.id || project.projectId,
    name: project.name || project.label || project.path || 'Проект',
    roots: project.roots?.length ? project.roots : project.path ? [{ path: project.path }] : [],
  }));
}

async function createDesktopThread(input) {
  const projects = input.projectless === true ? [] : await listDesktopProjects();
  const wanted = normalizeLocalPath(input.cwd || cwd);
  const project = input.projectless === true ? null : input.projectId
    ? projects.find(candidate => candidate.id === input.projectId)
    : projects.find(candidate => (candidate.roots || []).some(root => normalizeLocalPath(root.path || root) === wanted));
  if (input.projectId && !project) throw Object.assign(new Error('Desktop project not found'), { status: 404 });
  const target = project
    ? { type: 'project', projectId: project.id, environment: { type: 'local' } }
    : { type: 'projectless' };
  const args = {
    prompt: String(input.prompt || '').trim(),
    target,
    ...(String(input.name || '').trim() ? { title: String(input.name).trim().slice(0, 120) } : {}),
    ...(typeof input.model === 'string' && input.model ? { model: input.model } : {}),
  };
  if (!args.prompt) throw Object.assign(new Error('Initial prompt is empty'), { status: 400 });
  const data = parseAppToolsJson(await callDesktopTool('create_thread', args));
  if (!data.threadId) throw new Error(data.clientThreadId ? 'Desktop thread is still provisioning; refresh the list shortly' : 'Codex Desktop did not return a thread id');
  let desktopNavigated = false;
  let desktopNavigationError = '';
  try { desktopNavigated = await navigateDesktopThread(data.threadId); }
  catch (error) { desktopNavigationError = error.message; }
  publish({ type: 'thread-created', threadId: data.threadId, desktopNavigated });
  let thread = { id: data.threadId, model: input.model || null };
  try { thread = await readThread(data.threadId, false); }
  catch { /* Creation succeeded; history can be read separately. */ }
  return {
    ...thread,
    hostId: data.hostId || appToolsContextHostId,
    desktopAppTools: true,
    desktopNavigated,
    ...(desktopNavigationError ? { desktopNavigationError } : {}),
  };
}

async function navigateDesktopThread(threadId) {
  const result = parseAppToolsJson(await callDesktopTool('navigate_to_codex_page', { threadId }));
  return Boolean(result.navigated);
}

function normalizeLocalPath(value) {
  let normalized = String(value || '').trim().replaceAll('\\', '/').toLocaleLowerCase('ru');
  if (normalized.startsWith('//?/unc/')) normalized = `//${normalized.slice(8)}`;
  else if (normalized.startsWith('//?/') || normalized.startsWith('//./')) normalized = normalized.slice(4);
  const isUnc = normalized.startsWith('//');
  normalized = normalized.replace(/\/{2,}/g, '/');
  if (isUnc) normalized = `/${normalized}`;
  return normalized.replace(/\/+$/, '');
}

function publish(event) {
  const id = ++eventSequence;
  const line = `id: ${eventEpoch}:${id}\ndata: ${JSON.stringify(event)}\n\n`;
  recentEvents.push({ id, line });
  if (recentEvents.length > 100) recentEvents.shift();
  for (const response of subscribers) {
    if (!response.write(line)) response.destroy();
  }
}

function startLocalStoreWatcher() {
  if (!appToolsContextThreadId || !process.env.CODEX_HOME) return;
  try {
    localStoreWatcher = watch(process.env.CODEX_HOME, { persistent: false }, (_eventType, filename) => {
      const name = String(filename || '').replaceAll('\\', '/').split('/').at(-1);
      if (name !== 'state_5.sqlite' && name !== 'state_5.sqlite-wal') return;
      clearTimeout(localStoreEventTimer);
      localStoreEventTimer = setTimeout(() => publish({ type: 'desktop-store-changed' }), 160);
    });
    localStoreWatcher.on('error', () => { localStoreWatchSupported = false; });
    localStoreWatchSupported = true;
  } catch {
    localStoreWatcher = null;
    localStoreWatchSupported = false;
  }
}

function failPending(error) {
  for (const item of pending.values()) item.reject(error);
  pending.clear();
}

function handleMessage(message) {
  if (message.id !== undefined && pending.has(message.id)) {
    const request = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) request.reject(Object.assign(new Error(message.error.message || 'App Server error'), { rpc: message.error }));
    else request.resolve(message.result);
    return;
  }
  if (message.method) {
    if (message.id !== undefined) {
      approvals.set(String(message.id), message);
      publish({ type: 'server-request', requestId: String(message.id), method: message.method, params: message.params });
    } else {
      publish({ type: 'notification', method: message.method, params: message.params });
    }
  }
}

codex.stdout.setEncoding('utf8');
codex.stdout.on('data', chunk => {
  stdoutBuffer += chunk;
  let newline;
  while ((newline = stdoutBuffer.indexOf('\n')) >= 0) {
    const line = stdoutBuffer.slice(0, newline).trim();
    stdoutBuffer = stdoutBuffer.slice(newline + 1);
    if (!line) continue;
    try { handleMessage(JSON.parse(line)); }
    catch (error) { publish({ type: 'transport-error', message: `Invalid App Server response: ${error.message}` }); }
  }
});
codex.stderr.setEncoding('utf8');
codex.stderr.on('data', chunk => publish({ type: 'server-log', message: chunk.slice(0, 1200) }));
codex.on('error', error => { ready = false; failPending(error); publish({ type: 'transport-error', message: error.message }); });
codex.on('exit', (code, signal) => { ready = false; failPending(new Error(`App Server exited (${code ?? signal})`)); publish({ type: 'transport-error', message: `App Server process exited (${code ?? signal})` }); });

function rpc(method, params = {}, timeoutMs = 30000) {
  if (!ready && method !== 'initialize') return Promise.reject(new Error('App Server is not ready'));
  const id = nextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out`)); }, timeoutMs);
    pending.set(id, {
      resolve: value => { clearTimeout(timer); resolve(value); },
      reject: error => { clearTimeout(timer); reject(error); },
    });
    codex.stdin.write(`${JSON.stringify({ id, method, params })}\n`, error => {
      if (error) { pending.delete(id); clearTimeout(timer); reject(error); }
    });
  });
}

function notify(method, params) {
  codex.stdin.write(`${JSON.stringify({ method, params })}\n`);
}

const initialized = rpc('initialize', {
  clientInfo: { name: 'codex-localhost', title: 'Codex Localhost', version: '0.1.0' },
  capabilities: { experimentalApi: true },
}).then(result => {
  ready = true;
  appServerVersion = result.userAgent || 'unknown';
  notify('initialized', {});
  publish({ type: 'ready', userAgent: appServerVersion, codexHome: result.codexHome, cwd });
  return result;
});
initialized.catch(() => {});

function json(response, status, value) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
  response.end(JSON.stringify(value));
}

async function body(request) {
  let raw = '';
  request.setEncoding('utf8');
  for await (const chunk of request) {
    raw += chunk;
    if (Buffer.byteLength(raw) > 1_000_000) throw Object.assign(new Error('Request body is too large'), { status: 413 });
  }
  try {
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error();
    return parsed;
  }
  catch { throw Object.assign(new Error('Invalid JSON body'), { status: 400 }); }
}

function threadSummary(thread) {
  return {
    id: thread.id,
    title: thread.name || thread.preview?.split(/\r?\n/)[0]?.slice(0, 120) || 'Новый чат',
    preview: thread.preview || '',
    cwd: thread.cwd,
    updatedAt: thread.updatedAt,
    status: thread.status,
    model: thread.model,
    ephemeral: thread.ephemeral,
    projectId: thread.projectId || null,
    hostId: thread.hostId || null,
    desktopAppTools: Boolean(thread.desktopAppTools),
    source: thread.source,
    path: thread.path,
  };
}

function pageThreads(result) {
  const seen = new Set();
  return {
    threads: (result.data || []).filter(thread => {
      if (seen.has(thread.id)) return false;
      seen.add(thread.id);
      return true;
    }).map(threadSummary),
    nextCursor: result.nextCursor || null,
    appServerVersion,
  };
}

function delegatedPrompt(item) {
  if (item?.type !== 'functionCallOutput' || !['create_thread', 'send_message_to_thread'].includes(item.name)) return null;
  const match = String(item.output || '').match(/<input>([\s\S]*?)<\/input>/);
  if (!match) return null;
  return match[1]
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');
}

async function listThreads(url, cwd = undefined) {
  // Start both read-only catalogs together. The Desktop app-tools list can be
  // much slower than the App Server page, so serializing them delays the first
  // useful sidebar render without improving consistency.
  const desktopThreadsPromise = !cwd && appToolsContextThreadId
    ? listDesktopThreads().then(value => ({ value }), error => ({ error }))
    : null;
  const sourceKinds = url.searchParams.getAll('sourceKind').filter(Boolean);
  const result = await rpc('thread/list', {
    limit: Math.min(100, Math.max(1, Number(url.searchParams.get('limit') || 50))),
    sortKey: 'updated_at',
    sortDirection: 'desc',
    cursor: url.searchParams.get('cursor') || null,
    archived: false,
    ...(cwd ? { cwd } : {}),
    ...(sourceKinds.length ? { sourceKinds } : {}),
  });
  const page = pageThreads(result);
  if (cwd || !appToolsContextThreadId) return page;
  try {
    const desktopResult = await desktopThreadsPromise;
    if (desktopResult.error) throw desktopResult.error;
    const desktopThreads = desktopResult.value;
    const merged = new Map(page.threads.map(thread => [thread.id, thread]));
    for (const thread of desktopThreads) {
      const appServerThread = merged.get(thread.id);
      // The Desktop listing can omit projectId even when App Server still
      // knows the assignment. Preserve that assignment for project grouping.
      merged.set(thread.id, {
        ...appServerThread,
        ...thread,
        projectId: thread.projectId || appServerThread?.projectId || null,
      });
    }
    return { ...page, threads: [...merged.values()].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0)), desktopAppTools: true, desktopListStale: Date.now() - desktopThreadsCachedAt > 30000 };
  } catch (error) {
    return { ...page, desktopAppTools: false, desktopAppToolsError: error.message };
  }
}

async function listProjectThreads(projectId, url) {
  let project = null;
  try { project = (await rpc('project/read', { projectId })).project || null; }
  catch (error) {
    if (!/not found/i.test(error.message)) throw error;
  }
  if (!project && appToolsContextThreadId) {
    project = (await listDesktopProjects()).find(candidate => candidate.id === projectId) || null;
  }
  if (!project) throw Object.assign(new Error('Project not found'), { status: 404 });
  const cwd = (project.roots || []).map(root => typeof root === 'string' ? root : root.path).filter(Boolean);
  if (!cwd.length) return { threads: [], nextCursor: null, appServerVersion };
  const page = await listThreads(url, cwd.length === 1 ? cwd[0] : cwd);
  if (!appToolsContextThreadId) return page;
  try {
    const normalizedRoots = cwd.map(normalizeLocalPath);
    const desktopThreads = (await listDesktopThreads()).filter(thread =>
      thread.projectId === projectId || normalizedRoots.some(root => {
        const threadCwd = normalizeLocalPath(thread.cwd);
        return threadCwd === root || threadCwd.startsWith(`${root}/`);
      }));
    const merged = new Map(page.threads.map(thread => [thread.id, thread]));
    for (const thread of desktopThreads) {
      const appServerThread = merged.get(thread.id);
      merged.set(thread.id, {
        ...appServerThread,
        ...thread,
        projectId: thread.projectId || appServerThread?.projectId || projectId,
      });
    }
    return { ...page, threads: [...merged.values()].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0)), desktopAppTools: true };
  } catch { return { ...page, desktopAppTools: false }; }
}

function mapStoredItem(item) {
  const prompt = delegatedPrompt(item);
  if (prompt !== null) return { id: item.id, role: 'user', text: prompt };
  if (item.type === 'userMessage') return { id: item.id, role: 'user', text: (item.content || []).map(part => part.text || (part.type === 'image' ? '[изображение]' : '')).join('') };
  if (item.type === 'agentMessage') return { id: item.id, role: 'assistant', text: item.text || '', phase: item.phase };
  if (item.type === 'commandExecution') return { id: item.id, role: 'tool', text: `${item.command}\n${item.aggregatedOutput || ''}`, status: item.status };
  if (item.type === 'fileChange') return { id: item.id, role: 'tool', text: `Изменение файлов (${item.changes?.length || 0})`, status: item.status };
  return { id: item.id, role: 'tool', text: `[${item.type}]` };
}

function mapStoredTurn(turn) {
  return { id: turn.id, status: turn.status, items: (turn.items || []).map(mapStoredItem) };
}

async function listThreadHistory(id, { cursor, limit = 20, itemsView = 'full', includeRaw = false } = {}) {
  const boundedLimit = Math.max(1, Math.min(50, Number.parseInt(limit, 10) || 50));
  const boundedItemsView = ['full', 'summary', 'notLoaded'].includes(itemsView) ? itemsView : 'full';
  let history = { data: [], nextCursor: null };
  try {
    history = await rpc('thread/turns/list', {
      threadId: id,
      limit: boundedLimit,
      sortDirection: 'desc',
      itemsView: boundedItemsView,
      ...(cursor ? { cursor } : {}),
    });
  } catch (error) {
    // A just-started thread is intentionally not persisted until its first turn.
    if (!error.message.includes('not materialized yet')) throw error;
  }
  const turns = [...(history.data || [])].reverse();
  return {
    turns: turns.map(mapStoredTurn),
    historyNextCursor: history.nextCursor || null,
    ...(includeRaw ? { rawTurns: turns } : {}),
  };
}

async function listThreadItems(id, { cursor, limit = 100, direction = 'desc', turnId } = {}) {
  const boundedLimit = Math.max(1, Math.min(100, Number.parseInt(limit, 10) || 100));
  const sortDirection = direction === 'asc' ? 'asc' : 'desc';
  const result = await rpc('thread/items/list', {
    threadId: id,
    limit: boundedLimit,
    sortDirection,
    ...(cursor ? { cursor } : {}),
    ...(turnId ? { turnId } : {}),
  });
  const data = result.data || [];
  if (sortDirection === 'desc') data.reverse();
  return {
    items: data.map(entry => ({ turnId: entry.turnId, item: mapStoredItem(entry.item) })),
    historyNextCursor: result.nextCursor || null,
  };
}

async function latestThreadTurnId(id) {
  const page = await listThreadHistory(id, { limit: 1, itemsView: 'notLoaded' });
  return page.turns.at(-1)?.id || null;
}

function groupHistoryItems(items, statuses) {
  const turns = new Map();
  for (const entry of items || []) {
    let turn = turns.get(entry.turnId);
    if (!turn) {
      turn = { id: entry.turnId, status: statuses.get(entry.turnId) || 'completed', items: [] };
      turns.set(entry.turnId, turn);
    }
    turn.items.push(entry.item);
  }
  return [...turns.values()];
}

async function readThreadTimeline(id, { cursor, limit = 100, tailOnly = false } = {}) {
  try {
    const [firstItemsPage, turnPage] = await Promise.all([
      listThreadItems(id, { cursor, limit, direction: 'desc' }),
      listThreadHistory(id, { limit: 50, itemsView: 'notLoaded' }),
    ]);
    const statuses = new Map((turnPage.turns || []).map(turn => [turn.id, turn.status]));
    let olderItems = [];
    let nextCursor = firstItemsPage.historyNextCursor;
    let pagesLoaded = 1;
    let conversationalItems = firstItemsPage.items.filter(entry => ['user', 'assistant'].includes(entry.item.role)).length;
    while (!tailOnly && nextCursor && conversationalItems < 10 && pagesLoaded < 3) {
      const olderPage = await listThreadItems(id, { cursor: nextCursor, limit, direction: 'desc' });
      olderItems = [...olderPage.items, ...olderItems];
      nextCursor = olderPage.historyNextCursor;
      pagesLoaded++;
      conversationalItems += olderPage.items.filter(entry => ['user', 'assistant'].includes(entry.item.role)).length;
      if (!olderPage.items.length) break;
    }
    return {
      turns: groupHistoryItems(firstItemsPage.items, statuses),
      olderTurns: groupHistoryItems(olderItems, statuses),
      historyNextCursor: nextCursor,
      historyMode: 'items',
    };
  } catch (error) {
    // Older App Server builds may not support item pagination for this store.
    const history = await listThreadHistory(id, { limit: 5, cursor });
    return { ...history, olderTurns: [], historyMode: 'turns', itemHistoryFallback: error.message };
  }
}

async function readThread(id, includeHistory = true, rawItems = false, tailOnly = false) {
  const result = await rpc('thread/read', { threadId: id, includeTurns: false });
  const thread = result.thread;
  if (!thread) throw Object.assign(new Error('Thread not found'), { status: 404 });
  if (!includeHistory) {
    return {
      id: thread.id,
      title: thread.name || thread.preview?.split(/\r?\n/)[0]?.slice(0, 120) || 'Новый чат',
      cwd: thread.cwd,
      status: thread.status,
      model: thread.model,
      ephemeral: thread.ephemeral,
      projectId: thread.projectId || null,
    };
  }
  const history = await readThreadTimeline(id, { tailOnly });
  const rawHistory = rawItems ? await listThreadHistory(id, { limit: 5, includeRaw: true }) : null;
  return {
    id: thread.id,
    title: thread.name || thread.preview?.split(/\r?\n/)[0]?.slice(0, 120) || 'Новый чат',
    cwd: thread.cwd,
    status: thread.status,
    model: thread.model,
    ephemeral: thread.ephemeral,
    projectId: thread.projectId || null,
    ...history,
    ...(rawItems ? { rawTurns: rawHistory.rawTurns } : {}),
  };
}

async function ensureThreadLoaded(id) {
  if (startedThreads.has(id) || resumedThreads.has(id)) return;
  await rpc('thread/resume', { threadId: id });
  resumedThreads.add(id);
}

function operationView(operation) {
  const { id, threadId, state, createdAt, updatedAt, userDelivered, assistantResponse, lastError } = operation;
  return { id, threadId, state, createdAt, updatedAt, userDelivered, assistantResponse, ...(lastError ? { lastError } : {}) };
}

function startDeliveryTracking(threadId, prompt, baselineTurnId = null) {
  const now = Date.now();
  for (const [id, op] of operations) {
    if (op.done && now - op.updatedAt > 60 * 60 * 1000) operations.delete(id);
  }
  const operation = { id: randomUUID(), threadId, prompt, baselineTurnId, state: 'accepted', createdAt: now, updatedAt: now, userDelivered: false, assistantResponse: false, done: false, terminalSince: 0 };
  operations.set(operation.id, operation);
  activeThreadOperations.set(threadId, operation.id);
  const poll = async () => {
    if (operation.done) return;
    const oldState = operation.state;
    try {
      const history = await readThreadTimeline(threadId, { tailOnly: true });
      const turns = history.turns || [];
      const baselineIndex = baselineTurnId ? turns.findIndex(turn => turn.id === baselineTurnId) : -1;
      const matchingTurn = turns.find((turn, index) =>
        (!baselineTurnId || baselineIndex < 0 || index > baselineIndex)
        && (turn.items || []).some(item => item.role === 'user' && item.text === prompt));
      if (matchingTurn) {
        operation.userDelivered = true;
        const assistants = (matchingTurn.items || []).filter(item => item.role === 'assistant' && item.text?.trim());
        operation.assistantResponse = assistants.some(item => item.phase === 'final_answer')
          || (matchingTurn.status === 'completed' && assistants.some(item => !item.phase));
        if (operation.assistantResponse) { operation.state = 'completed'; operation.done = true; }
        else if (['failed', 'interrupted'].includes(matchingTurn.status)) {
          operation.terminalSince ||= Date.now();
          if (Date.now() - operation.terminalSince >= 5000) { operation.state = 'failed'; operation.done = true; }
          else operation.state = 'delivered';
        } else { operation.terminalSince = 0; operation.state = 'delivered'; }
      }
      operation.lastError = null;
    } catch (error) { operation.lastError = error.message; }
    if (!operation.done && Date.now() - operation.createdAt >= 180000) {
      operation.state = 'unconfirmed'; operation.done = true;
    }
    if (operation.state !== oldState || operation.done) {
      operation.updatedAt = Date.now();
      publish({ type: 'operation-updated', operation: operationView(operation) });
    }
    if (operation.done && activeThreadOperations.get(threadId) === operation.id) activeThreadOperations.delete(threadId);
    if (!operation.done) { operation.timer = setTimeout(poll, 2800); operation.timer.unref(); }
  };
  operation.timer = setTimeout(poll, 500);
  operation.timer.unref();
  return operationView(operation);
}

function localOrigin(origin) {
  try {
    const url = new URL(origin);
    return ['http:', 'https:'].includes(url.protocol)
      && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      && url.origin === origin;
  } catch { return false; }
}

const server = createServer(async (request, response) => {
  const host = request.headers.host || '';
  let hostname = '';
  try { hostname = new URL(`http://${host}`).hostname; } catch {}
  if (!['localhost', '127.0.0.1', '[::1]'].includes(hostname)) return json(response, 403, { error: 'Loopback Host required' });
  const origin = request.headers.origin;
  if (origin && (!localOrigin(origin) || new URL(origin).host !== host)) return json(response, 403, { error: 'Same-origin loopback requests only' });
  const apiToken = process.env.CODEX_LOCAL_API_TOKEN;
  if (apiToken && request.headers.authorization !== `Bearer ${apiToken}`) return json(response, 401, { error: 'Local API token required' });
  if (origin) {
    response.setHeader('Access-Control-Allow-Origin', origin);
    response.setHeader('Vary', 'Origin');
    response.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    response.setHeader('Access-Control-Allow-Headers', 'Content-Type, Last-Event-ID');
  }
  if (request.method === 'OPTIONS') { response.writeHead(204); return response.end(); }
  if (request.method === 'POST' && (Number(request.headers['content-length']) > 0 || request.headers['transfer-encoding'])
      && !/^application\/json(?:\s*;|$)/i.test(request.headers['content-type'] || '')) {
    return json(response, 415, { error: 'Use application/json' });
  }
  const url = new URL(request.url, 'http://localhost');
  if (request.method === 'GET' && url.pathname === '/api/status') {
  return json(response, 200, {
    ready,
    apiVersion: '1.0',
    appServerVersion,
    transport: 'Codex Desktop app-tools named pipe for native chat operations; managed App Server control socket for history',
    cwd,
    desktopHostId: appToolsContextHostId || null,
    pendingApprovals: approvals.size,
    capabilities: { projectScopedThreads: true, desktopAppTools: Boolean(appToolsContextThreadId), desktopHistoryInput: Boolean(appToolsContextThreadId), desktopStoreEvents: localStoreWatchSupported, projectlessThreadCreation: Boolean(appToolsContextThreadId) },
  });
  }
  if (request.method === 'GET' && url.pathname === '/api/desktop/status') {
    try {
      if (!appToolsContextThreadId) throw new Error('Desktop bridge context is not configured');
      const [host, latestTurnId] = await Promise.all([
        appToolsRpc('tools/list', { threadStartKind: 'all' }),
        latestThreadTurnId(appToolsContextThreadId),
      ]);
      const names = (host.tools || []).map(tool => tool.name);
      return json(response, 200, {
        ready: Boolean(latestTurnId && names.includes('list_threads') && names.includes('create_thread') && names.includes('send_message_to_thread')),
        transport: 'Codex Desktop app-tools named pipe',
        toolCount: names.length,
        capabilities: { listThreads: names.includes('list_threads'), readThreads: names.includes('read_thread'), createThreads: names.includes('create_thread'), sendMessages: names.includes('send_message_to_thread') },
      });
    } catch (error) {
      return json(response, 503, { ready: false, transport: 'Codex Desktop app-tools named pipe', error: error.message });
    }
  }
  if (request.method === 'POST' && url.pathname === '/api/projects') {
    try {
      await initialized;
      const input = await body(request);
      const name = String(input.name || '').trim().slice(0, 120);
      const path = String(input.path || '').trim();
      if (!name || !path || !/^(?:[A-Za-z]:[\\/]|\\\\)/.test(path)) {
        return json(response, 400, { error: 'Project name and an absolute local root are required' });
      }
      const result = await rpc('project/create', {
        name,
        roots: [{ path }],
        idempotencyKey: String(input.idempotencyKey || randomUUID()),
      });
      publish({ type: 'project-created', projectId: result.project?.id });
      return json(response, 201, { project: result.project });
    } catch (error) { return json(response, error.status || 500, { error: error.message, rpc: error.rpc }); }
  }
    if (request.method === 'GET' && url.pathname === '/api/projects') {
      const ids = [...new Set((url.searchParams.get('ids') || '').split(',').map(id => id.trim()).filter(Boolean))].slice(0, 40);
      if (ids.length === 0) {
        const result = await rpc('project/list', { limit: 100 });
        let projects = result.data || result.projects || [];
        if (appToolsContextThreadId) {
          try {
            const desktopProjects = await listDesktopProjects();
            const roots = new Set(projects.flatMap(project => (project.roots || []).map(root => normalizeLocalPath(root.path || root))));
            projects = [...desktopProjects, ...projects.filter(project => !(project.roots || []).some(root => roots.has(normalizeLocalPath(root.path || root))))];
          } catch { /* Keep the App Server catalog when Desktop tools are unavailable. */ }
        }
        return json(response, 200, { projects, nextCursor: result.nextCursor || null });
      }
      let projects = await Promise.all(ids.map(async projectId => {
        try { return (await rpc('project/read', { projectId })).project || null; }
        catch (error) {
          if (/not found/i.test(error.message)) return null;
          throw error;
        }
      }));
      projects = projects.filter(Boolean);
      if (appToolsContextThreadId && projects.length < ids.length) {
        try {
          const desktopProjects = await listDesktopProjects();
          const found = new Set(projects.map(project => project.id));
          projects.push(...desktopProjects.filter(project => ids.includes(project.id) && !found.has(project.id)));
        } catch { /* Keep successfully read App Server projects. */ }
      }
      return json(response, 200, { projects });
    }
  if (request.method === 'GET' && url.pathname === '/api/models') {
    try { return json(response, 200, await rpc('model/list', { limit: 100, includeHidden: false })); }
    catch (error) { return json(response, 500, { error: error.message, rpc: error.rpc }); }
  }
  if (request.method === 'GET' && url.pathname === '/api/loaded') {
    try { return json(response, 200, await rpc('thread/loaded/list', { limit: 100 })); }
    catch (error) { return json(response, 500, { error: error.message, rpc: error.rpc }); }
  }
  if (request.method === 'GET' && url.pathname === '/api/events') {
    response.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
    response.write('retry: 3000\n: connected\n\n');
    const lastEventId = request.headers['last-event-id'];
    if (lastEventId) {
      const match = String(lastEventId).match(/^([0-9a-f-]+):(\d+)$/i);
      const lastId = match ? Number(match[2]) : NaN;
      if (!match || match[1] !== eventEpoch || !Number.isSafeInteger(lastId) || lastId > eventSequence || (recentEvents.length && lastId < recentEvents[0].id - 1)) {
        response.write(`data: ${JSON.stringify({ type: 'replay-reset' })}\n\n`);
      } else for (const event of recentEvents) if (event.id > lastId) response.write(event.line);
    }
    subscribers.add(response);
    const heartbeat = setInterval(() => { if (!response.write(': heartbeat\n\n')) response.destroy(); }, 15000);
    heartbeat.unref();
    request.on('close', () => { clearInterval(heartbeat); subscribers.delete(response); });
    return;
  }
  const operationMatch = url.pathname.match(/^\/api\/operations\/([^/]+)$/);
  if (request.method === 'GET' && operationMatch) {
    const operation = operations.get(operationMatch[1]);
    return operation ? json(response, 200, operationView(operation)) : json(response, 404, { error: 'Operation not found' });
  }
  try {
    await initialized;
    if (request.method === 'GET' && url.pathname === '/api/desktop-history') {
      try { return json(response, 200, listIndexedDesktopThreads(url)); }
      catch (error) { return json(response, error.status || 503, { error: error.message }); }
    }
    if (request.method === 'GET' && url.pathname === '/api/threads') {
      const scope = url.searchParams.get('scope') || (appToolsContextThreadId ? 'desktop' : 'all');
      if (!['desktop', 'all'].includes(scope)) return json(response, 400, { error: 'scope must be desktop or all' });
      const result = await listThreads(url);
      if (scope === 'desktop') {
        if (!result.desktopAppTools) return json(response, 503, { error: result.desktopAppToolsError || 'Desktop catalog unavailable' });
        return json(response, 200, { ...result, threads: result.threads.filter(thread => thread.desktopAppTools), nextCursor: null, scope });
      }
      return json(response, 200, { ...result, scope });
    }
    const projectThreadsMatch = url.pathname.match(/^\/api\/projects\/([^/]+)\/threads$/);
    if (request.method === 'GET' && projectThreadsMatch) {
      const projectId = decodeURIComponent(projectThreadsMatch[1]);
      return json(response, 200, await listProjectThreads(projectId, url));
    }
    const historyPageMatch = url.pathname.match(/^\/api\/threads\/([^/]+)\/history$/);
    if (request.method === 'GET' && historyPageMatch) {
      const id = decodeURIComponent(historyPageMatch[1]);
      if (!id || id.includes('/')) return json(response, 400, { error: 'Invalid thread id' });
      const page = await listThreadHistory(id, {
        cursor: url.searchParams.get('cursor') || undefined,
        limit: url.searchParams.get('limit') || 20,
        itemsView: url.searchParams.get('itemsView') || 'full',
      });
      return json(response, 200, { id, ...page });
    }
    const historyItemsMatch = url.pathname.match(/^\/api\/threads\/([^/]+)\/items$/);
    if (request.method === 'GET' && historyItemsMatch) {
      const id = decodeURIComponent(historyItemsMatch[1]);
      if (!id || id.includes('/')) return json(response, 400, { error: 'Invalid thread id' });
      const page = await listThreadItems(id, {
        cursor: url.searchParams.get('cursor') || undefined,
        limit: url.searchParams.get('limit') || 100,
        direction: url.searchParams.get('direction') || 'desc',
        turnId: url.searchParams.get('turnId') || undefined,
      });
      return json(response, 200, { id, ...page });
    }
    if (request.method === 'GET' && url.pathname.startsWith('/api/threads/')) {
      const id = decodeURIComponent(url.pathname.slice('/api/threads/'.length));
      if (id === 'undefined' || id.includes('/')) return json(response, 400, { error: 'Invalid thread id' });
      return json(response, 200, await readThread(
        id,
        url.searchParams.get('metadata') !== '1',
        url.searchParams.get('raw') === '1',
        url.searchParams.get('tail') === '1',
      ));
    }
    if (request.method === 'POST' && url.pathname === '/api/threads') {
      const input = await body(request);
      if (typeof input.prompt !== 'string' || !input.prompt.trim()) return json(response, 400, { error: 'Initial prompt is required' });
      if (input.transport && !['desktop', 'app-server'].includes(input.transport)) return json(response, 400, { error: 'Invalid transport' });
      if (input.transport !== 'app-server') {
        if (!appToolsContextThreadId) return json(response, 503, { error: 'Desktop bridge is unavailable' });
        if (input.projectless && input.projectId) return json(response, 400, { error: 'Choose projectless or projectId' });
        try {
          const thread = await createDesktopThread(input);
          const operation = startDeliveryTracking(thread.id, String(input.prompt).trim());
          return json(response, 201, { ...thread, initialPromptSubmitted: true, operation });
        } catch (error) {
          if (/timed out/i.test(error.message)) return json(response, 504, { error: error.message, deliveryUnknown: true });
          throw error;
        }
      }
      const result = await rpc('thread/start', {
        cwd: input.projectless === true ? cwd : input.cwd || cwd,
        threadSource: 'appServer',
        ephemeral: false,
        approvalPolicy: input.approvalPolicy || 'onRequest',
        ...(input.permissions ? {permissions:input.permissions, config:input.config || {}} : {sandbox: input.sandbox || 'workspace-write'}),
        ...(typeof input.model === 'string' && input.model ? { model: input.model } : {}),
      });
      const threadId = result.thread?.id;
      if (!threadId) throw new Error('App Server did not return a thread id');
      const name = String(input.name || '').trim().slice(0, 120);
      if (name) {
        try { await rpc('thread/name/set', { threadId, name }); }
        catch { /* Naming is optional on older App Server builds. */ }
      }
      startedThreads.add(threadId);
      publish({ type: 'thread-created', threadId });
      try {
        const turn = await rpc('turn/start', {
          threadId,
          input: [{ type: 'text', text: input.prompt.trim() }],
          approvalPolicy: input.approvalPolicy || 'on-request',
          ...(input.permissions ? {permissions:input.permissions} : (input.sandboxPolicy && typeof input.sandboxPolicy === 'object' ? { sandboxPolicy: input.sandboxPolicy } : {})),
        });
        const operation = startDeliveryTracking(threadId, input.prompt.trim());
        return json(response, 201, { id: threadId, model: input.model || null, turnId: turn.turn?.id, initialPromptSubmitted: true, transport: 'app-server', operation });
      } catch (error) {
        return json(response, 502, { error: error.message, threadId, deliveryUnknown: /timed out/i.test(error.message) });
      }
    }
    const desktopOpenMatch = url.pathname.match(/^\/api\/threads\/([^/]+)\/desktop\/open$/);
    if (request.method === 'POST' && desktopOpenMatch) {
      if (!appToolsContextThreadId) return json(response, 503, { error: 'Codex Desktop bridge is unavailable' });
      const threadId = decodeURIComponent(desktopOpenMatch[1]);
      const inRecentDesktopList = (await listDesktopThreads()).some(thread => thread.id === threadId);
      let inDesktopHistoryIndex = false;
      if (!inRecentDesktopList) {
        try { inDesktopHistoryIndex = isIndexedDesktopThread(threadId); }
        catch { /* Keep recent Desktop navigation available if the local index is unavailable. */ }
      }
      if (!inRecentDesktopList && !inDesktopHistoryIndex) {
        return json(response, 404, { error: 'Desktop thread not found' });
      }
      const navigated = await navigateDesktopThread(threadId);
      return json(response, 200, { threadId, navigated, transport: 'desktop-app-tools' });
    }
    const openMatch = url.pathname.match(/^\/api\/threads\/([^/]+)\/open$/);
    if (request.method === 'POST' && openMatch) {
      const threadId = decodeURIComponent(openMatch[1]);
      await ensureThreadLoaded(threadId);
      return json(response, 200, await readThread(threadId));
    }
    const messageMatch = url.pathname.match(/^\/api\/threads\/([^/]+)\/messages$/);
    if (request.method === 'POST' && messageMatch) {
      const threadId = decodeURIComponent(messageMatch[1]);
      const input = await body(request);
      if (typeof input.text !== 'string' || !input.text.trim()) return json(response, 400, { error: 'Message is empty' });
      if (input.transport && !['desktop', 'app-server'].includes(input.transport)) return json(response, 400, { error: 'Invalid transport' });
      const prompt = String(input.text).trim();
      const activeOperationId = activeThreadOperations.get(threadId);
      if (activeOperationId || threadSendInFlight.has(threadId)) return json(response, 409, { error: 'A message is already being processed for this thread', ...(activeOperationId ? { operationId: activeOperationId } : {}) });
      threadSendInFlight.add(threadId);
      try {
      const baselineTurnId = await latestThreadTurnId(threadId);
      if (input.transport !== 'app-server' && appToolsContextThreadId) {
        let sending = false;
        try {
          const navigated = await navigateDesktopThread(threadId);
          if (!navigated) return json(response, 409, { error: 'Desktop did not open this thread; message was not sent' });
          sending = true;
          const data = parseAppToolsJson(await callDesktopTool('send_message_to_thread', {
            threadId,
            hostId: input.hostId || appToolsContextHostId,
            prompt,
          }));
          publish({ type: 'turn-started', threadId, desktopAppTools: true });
          const operation = startDeliveryTracking(threadId, prompt, baselineTurnId);
          return json(response, 202, { threadId: data.threadId || threadId, status: 'accepted', transport: 'desktop-app-tools', operation });
        } catch (error) {
          if (sending && /timed out/i.test(error.message)) return json(response, 504, { error: error.message, deliveryUnknown: true });
          throw error;
        }
      }
      if (input.transport === 'desktop') return json(response, 503, { error: 'Desktop bridge is unavailable' });
      await ensureThreadLoaded(threadId);
      const result = await rpc('turn/start', { threadId, input: [{ type: 'text', text: prompt }] });
      publish({ type: 'turn-started', threadId, turnId: result.turn?.id });
      const operation = startDeliveryTracking(threadId, prompt, baselineTurnId);
      return json(response, 202, { threadId, turnId: result.turn?.id, status: 'accepted', transport: 'app-server', operation });
      } finally { threadSendInFlight.delete(threadId); }
    }
    if (request.method === 'GET' && url.pathname === '/api/approvals') return json(response, 200, [...approvals].map(([requestId, item]) => ({ requestId, method: item.method, params: item.params })));
    const approvalMatch = url.pathname.match(/^\/api\/approvals\/([^/]+)$/);
    if (request.method === 'POST' && approvalMatch) {
      const requestId = decodeURIComponent(approvalMatch[1]);
      if (!approvals.has(requestId)) return json(response, 404, { error: 'Approval request not found' });
      const input = await body(request);
      if (!['accept', 'decline'].includes(input.decision)) return json(response, 400, { error: 'decision must be accept or decline' });
      codex.stdin.write(`${JSON.stringify({ id: Number(requestId), result: { decision: input.decision === 'decline' ? 'decline' : 'accept' } })}\n`);
      approvals.delete(requestId);
      publish({ type: 'approval-resolved', requestId });
      return json(response, 200, { ok: true });
    }
    return json(response, 404, { error: 'Not found' });
  } catch (error) {
    json(response, error.status || 500, { error: error.message, rpc: error.rpc });
  }
});

startLocalStoreWatcher();
server.listen(Number(process.env.PORT || 4173), '127.0.0.1', () => {
  console.log(`Codex Localhost available at http://127.0.0.1:${server.address().port}`);
});

async function shutdown() {
  server.close();
  try { codex.stdin.end(); } catch {}
  setTimeout(() => { if (!codex.killed) codex.kill(); }, 1500).unref();
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
