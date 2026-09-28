/** Synthetic HTTP wrapper around the real pinned WITS route and bearer auth. */
import { createServer } from 'node:http'
import { AsyncLocalStorage } from 'node:async_hooks'
Object.assign(globalThis, { AsyncLocalStorage })
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
const root = process.env.WITS_SOURCE_ROOT!
const seed = JSON.parse(await readFile(process.env.WITS_HTTP_SYNTHETIC_SEED!, 'utf8'))
const { prisma } = await import(pathToFileURL(path.join(root, 'lib/db/prisma.ts')).href)
const { hashAgentApiKey } = await import(pathToFileURL(path.join(root, 'lib/agents/keys.ts')).href)
const { NextRequest } = await import(pathToFileURL(path.join(root, 'node_modules/next/server.js')).href)
const { POST } = await import(pathToFileURL(path.join(root, 'app/api/agent/coordination/sync/route.ts')).href)
const { POST: claimPost } = await import(pathToFileURL(path.join(root, 'app/api/agent/coordination/claims/route.ts')).href)
const { workAsyncStorage } = await import(pathToFileURL(path.join(root, 'node_modules/next/dist/server/app-render/work-async-storage.external.js')).href)
const { AfterContext } = await import(pathToFileURL(path.join(root, 'node_modules/next/dist/server/after/after-context.js')).href)
const createdKeys: string[] = []
for (const project of seed.projects) await prisma.project.create({ data: project })
for (const key of seed.keys) {
  const created = await prisma.agentApiKey.create({ data: {
    project_id: key.projectId, name: 'synthetic-am153-http',
    key_hash: hashAgentApiKey(key.token), key_prefix: key.token.slice(0, 8),
    participant_name: key.principal, principal_class: 'agent',
    coordination_principal_id: key.principal,
    coordination_access_label_record_id: key.labelRef.record_id,
    coordination_access_label_revision_digest: key.labelRef.revision_digest,
    capabilities: key.capabilities,
  } })
  createdKeys.push(created.id)
}
const server = createServer(async (request, response) => {
  try {
    if (!['/api/agent/coordination/sync', '/api/agent/coordination/claims'].includes(request.url || '') || request.method !== 'POST') {
      response.writeHead(404).end(); return
    }
    const chunks: Buffer[] = []
    for await (const chunk of request) chunks.push(Buffer.from(chunk))
    const callbacks: Array<() => void> = []
    const pending: Promise<unknown>[] = []
    const afterContext = new AfterContext({
      waitUntil: (job: Promise<unknown>) => { pending.push(job) },
      onClose: (callback: () => void) => { callbacks.push(callback) },
    })
    const handler = request.url === '/api/agent/coordination/claims' ? claimPost : POST
    const result = await workAsyncStorage.run({ afterContext }, () => handler(new NextRequest('http://localhost' + request.url, {
      method: 'POST', headers: {
        Authorization: request.headers.authorization || '', 'Content-Type': 'application/json',
      }, body: Buffer.concat(chunks),
    })))
    response.writeHead(result.status, { 'Content-Type': 'application/json' })
    response.end(await result.text())
    for (const callback of callbacks) callback()
    await Promise.all(pending)
  } catch {
    response.writeHead(500).end('{}')
  }
})
server.listen(0, '127.0.0.1', () => {
  const address = server.address() as { port: number }
  process.stdout.write(JSON.stringify({ port: address.port }) + '\n')
})
process.once('SIGTERM', () => {
  server.close(async () => {
    await prisma.agentApiKey.deleteMany({ where: { id: { in: createdKeys } } })
    await prisma.project.deleteMany({ where: { id: { in: seed.projects.map((p: {id: string}) => p.id) } } })
    await prisma.$disconnect(); process.exit(0)
  })
})
