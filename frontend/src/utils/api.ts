const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export type Stage = 'tenant' | 'competitors' | 'changes'

export type AnalysisStageEvent<T = unknown> = {
  type: 'stage'
  stage: Stage
  data: T
  progress?: number
}

export type AnalysisStatusEvent = {
  type: 'status'
  stage: string
  progress?: number
  message?: string
  data?: unknown
}

export type AnalysisStreamEvent = AnalysisStageEvent | AnalysisStatusEvent

export interface StartAnalysisOptions {
  monitorId?: string
  monitorName?: string
  tenantUrl?: string
  enableResearch?: boolean
  maxCompetitors?: number
  enableCaching?: boolean
}

export interface StartAnalysisResponse {
  taskId: string
  monitorId?: string
}

export interface MonitorSummary {
  id: string
  name: string
  url: string
  displayName?: string
  displayDomain?: string
  canonicalUrl?: string
  createdAt: string
  updatedAt?: string | null
  lastRunAt?: string | null
  latestTaskId?: string | null
  latestTaskStatus?: string | null
  latestTaskProgress?: number | null
  archivedAt?: string | null
  trackedCompetitorIds: string[]
  trackedCompetitorSlugs: string[]
  trackedCompetitorCount?: number
  hasTenant?: boolean
}

export interface ArchiveEntry {
  id: string
  title: string
  monitorId: string | null
  taskId: string | null
  createdAt: string
  tenant: unknown
  competitors: unknown
  changes: unknown
  metadata: Record<string, unknown> | null
}

export interface ArchiveCreateRequest {
  monitorId?: string
  taskId?: string
  title: string
  metadata?: Record<string, unknown>
}

export interface TaskResults {
  task_id: string
  status: string
  results: Record<string, unknown>
  started_at: string
  completed_at: string
}

export interface TenantSnapshot {
  id: string
  name: string
  url: string
  description: string
  targetMarket: string
  keyFeatures: string[]
}

export interface CompetitorInsight {
  id: string
  competitorId: string | null
  displayName: string
  primaryUrl: string
  briefDescription: string
  source: string
  confidence: number
  demographics: string
}

export interface CompetitorStageSnapshot {
  competitors: CompetitorInsight[]
  trackedCompetitorIds: string[]
}

export interface ChangeInsight {
  id: string
  url: string
  changeType: string
  content: string
  timestamp: string
  threatLevel: number
  whyMatter: string
  suggestions: string
  readAt: string | null
}

export interface TrackCompetitorOptions {
  monitorId: string
  displayName?: string
  url?: string
  source?: string
  description?: string
  confidence?: number
}

export interface TrackedCompetitor {
  id: string
  competitorId: string | null
  displayName: string
  primaryUrl: string
  briefDescription: string
  source: string
  demographics: string
  confidence?: number
}

export interface TrackCompetitorResponse {
  trackedCompetitorIds: string[]
  competitor?: TrackedCompetitor
}

export interface UntrackCompetitorResponse {
  trackedCompetitorIds: string[]
  untrackedCompetitorId?: string
}

export function adaptTenantStage(data: unknown): TenantSnapshot | null {
  if (!data || typeof data !== 'object') {
    return null
  }
  const record = data as Record<string, unknown>

  const name = coalesceString(record.tenant_name, 'Unknown company')
  const url = coalesceUrl(record.tenant_url)
  const description = coalesceString(record.tenant_description, `${name} overview pending.`)
  const targetMarket = coalesceString(record.target_market, 'Market pending')
  const keyFeaturesRaw = Array.isArray(record.key_features) ? record.key_features : []
  const keyFeatures = keyFeaturesRaw
    .filter((value): value is string => typeof value === 'string' && Boolean(value.trim()))
    .map((value) => value.trim())

  return {
    id: coalesceString(record.tenant_id, 'unknown'),
    name,
    url,
    description,
    targetMarket,
    keyFeatures,
  }
}

export function adaptCompetitorStage(data: unknown): CompetitorStageSnapshot {
  if (!data || typeof data !== 'object') {
    return { competitors: [], trackedCompetitorIds: [] }
  }

  const payload = data as Record<string, unknown>
  const rawCompetitors = Array.isArray(payload.competitors) ? payload.competitors : []
  const trackedIds = Array.isArray(payload.tracked_competitor_ids)
    ? (payload.tracked_competitor_ids as unknown[]).map((value) => String(value))
    : []

  const competitors = rawCompetitors
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .slice(0, 10)
    .map((competitor, index) => {
      const displayName = coalesceString(
        competitor.display_name ?? competitor.name,
        `Competitor ${index + 1}`
      )
      const primaryUrl = coalesceUrl(competitor.primary_url ?? competitor.url)
      const briefDescription = coalesceString(
        competitor.brief_description ?? competitor.description,
        'No briefing yet.'
      )
      const source = coalesceString(competitor.source, 'analysis')
      const confidenceValue = typeof competitor.confidence === 'number'
        ? competitor.confidence
        : parseFloat(String(competitor.confidence ?? 0.5))
      const confidence = Number.isFinite(confidenceValue) ? clamp(confidenceValue, 0, 1) : 0.5
      const demographics = coalesceString(
        competitor.demographics ?? competitor.target_users,
        'Undisclosed audience'
      )

      const id = coalesceString(
        competitor.id ?? competitor.competitor_id ?? competitor.domain ?? primaryUrl,
        `${displayName}-${index}`
      )
      const competitorId = typeof competitor.competitor_id === 'string'
        ? competitor.competitor_id
        : typeof competitor.id === 'string'
          ? competitor.id
          : null

      return {
        id,
        competitorId,
        displayName,
        primaryUrl,
        briefDescription,
        source,
        confidence,
        demographics,
      }
    })

  return {
    competitors,
    trackedCompetitorIds: trackedIds,
  }
}

export function adaptChangeStage(data: unknown): ChangeInsight[] {
  if (!data || typeof data !== 'object') {
    return []
  }

  const payload = data as Record<string, unknown>
  const list = Array.isArray(payload.changes) ? payload.changes : []

  return list
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((entry, index) => {
      const timestamp = coalesceString(entry.timestamp, new Date().toISOString())
      const threatLevel = typeof entry.threat_level === 'number'
        ? entry.threat_level
        : parseFloat(String(entry.threat_level ?? 5))

      return {
        id: coalesceString(entry.id, `change-${index}`),
        url: coalesceUrl(entry.url),
        changeType: coalesceString(entry.change_type, 'Modified'),
        content: coalesceString(entry.content, 'Details pending'),
        timestamp,
        threatLevel: Number.isFinite(threatLevel) ? threatLevel : 5,
        whyMatter: coalesceString(entry.why_matter, 'Impact assessment pending'),
        suggestions: coalesceString(entry.suggestions, 'Review with GTM team'),
        readAt:
          typeof entry.read_at === 'string' && entry.read_at.trim() ? entry.read_at : null,
      }
    })
}

function getAuthHeaders(): HeadersInit {
  if (typeof window === 'undefined') {
    return {}
  }
  const token = window.localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: string | undefined
    try {
      const payload = await response.json()
      detail = payload?.detail ?? payload?.message
    } catch {
      detail = response.statusText
    }
    throw new Error(detail || `Request failed with status ${response.status}`)
  }
  if (response.status === 204) {
    // @ts-expect-error allow void return
    return undefined
  }
  return (await response.json()) as T
}

export async function startAnalysis(companyName: string, options: StartAnalysisOptions = {}): Promise<StartAnalysisResponse> {
  const payload = {
    company_name: companyName,
    enable_research: options.enableResearch ?? true,
    max_competitors: options.maxCompetitors ?? 10,
    enable_caching: options.enableCaching ?? true,
    monitor_id: options.monitorId,
    monitor_name: options.monitorName,
    tenant_url: options.tenantUrl,
  }

  const response = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  })

  const data = await handleResponse<{ task_id: string; monitor_id?: string }>(response)
  return {
    taskId: data.task_id,
    monitorId: data.monitor_id,
  }
}

export async function fetchMonitors(): Promise<MonitorSummary[]> {
  const response = await fetch(`${API_BASE}/api/monitors`, {
    headers: {
      ...getAuthHeaders(),
    },
  })

  const data = await handleResponse<{ monitors: Array<Record<string, unknown>> }>(response)
  return data.monitors.map(mapMonitor)
}

export async function createMonitor(payload: { url: string; name?: string }): Promise<MonitorSummary> {
  const response = await fetch(`${API_BASE}/api/monitors`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  })

  const data = await handleResponse<Record<string, unknown>>(response)
  return mapMonitor(data)
}

export async function updateMonitorName(monitorId: string, name: string): Promise<MonitorSummary> {
  const response = await fetch(`${API_BASE}/api/monitors/${monitorId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ name }),
  })

  const data = await handleResponse<Record<string, unknown>>(response)
  return mapMonitor(data)
}

export async function deleteMonitor(monitorId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/monitors/${monitorId}`, {
    method: 'DELETE',
    headers: {
      ...getAuthHeaders(),
    },
  })
  await handleResponse(response)
}

export async function trackCompetitor(
  competitorId: string,
  options: TrackCompetitorOptions,
): Promise<TrackCompetitorResponse> {
  const response = await fetch(`${API_BASE}/api/competitors/${encodeURIComponent(competitorId)}/track`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({
      monitor_id: options.monitorId,
      display_name: options.displayName,
      url: options.url,
      source: options.source,
      description: options.description,
      confidence: options.confidence,
    }),
  })

  const data = await handleResponse<{
    tracked_competitor_ids?: unknown[]
    competitor?: Record<string, unknown>
  }>(response)

  return {
    trackedCompetitorIds: Array.isArray(data.tracked_competitor_ids)
      ? data.tracked_competitor_ids.map((value) => String(value))
      : [],
    competitor: data.competitor ? mapTrackedCompetitor(data.competitor) : undefined,
  }
}

export async function untrackCompetitor(
  competitorId: string,
  options: TrackCompetitorOptions,
): Promise<UntrackCompetitorResponse> {
  const response = await fetch(`${API_BASE}/api/competitors/${encodeURIComponent(competitorId)}/untrack`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ monitor_id: options.monitorId }),
  })

  const data = await handleResponse<{
    tracked_competitor_ids?: unknown[]
    untracked_competitor_id?: unknown
  }>(response)

  return {
    trackedCompetitorIds: Array.isArray(data.tracked_competitor_ids)
      ? data.tracked_competitor_ids.map((value) => String(value))
      : [],
    untrackedCompetitorId: data.untracked_competitor_id ? String(data.untracked_competitor_id) : undefined,
  }
}

export async function markChangeRead(changeId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/changes/${encodeURIComponent(changeId)}/read`, {
    method: 'POST',
    headers: {
      ...getAuthHeaders(),
    },
  })
  await handleResponse(response)
}

export async function bulkMarkChangesRead(changeIds: string[]): Promise<void> {
  const response = await fetch(`${API_BASE}/api/changes/bulk-read`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ change_ids: changeIds }),
  })
  await handleResponse(response)
}

export async function fetchArchives(): Promise<ArchiveEntry[]> {
  const response = await fetch(`${API_BASE}/api/archives`, {
    headers: {
      ...getAuthHeaders(),
    },
  })

  const data = await handleResponse<{ archives: Array<Record<string, unknown>> }>(response)
  return data.archives.map(mapArchive)
}

export async function createArchive(request: ArchiveCreateRequest): Promise<ArchiveEntry> {
  const response = await fetch(`${API_BASE}/api/archives`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({
      monitor_id: request.monitorId,
      task_id: request.taskId,
      title: request.title,
      metadata: request.metadata ?? {},
    }),
  })

  const data = await handleResponse<Record<string, unknown>>(response)
  return mapArchive(data)
}

export async function fetchTaskResults(taskId: string): Promise<TaskResults> {
  const response = await fetch(`${API_BASE}/api/results/${encodeURIComponent(taskId)}`, {
    headers: {
      ...getAuthHeaders(),
    },
  })

  return handleResponse<TaskResults>(response)
}

export async function* streamAnalysisEvents(taskId: string): AsyncGenerator<AnalysisStreamEvent> {
  const token = typeof window !== 'undefined' ? window.localStorage.getItem('auth_token') : null
  const wsUrl = buildWebSocketUrl(`/ws/analysis/${encodeURIComponent(taskId)}`, token ?? undefined)

  const socket = new WebSocket(wsUrl)

  await new Promise<void>((resolve, reject) => {
    const handleError = () => {
      cleanup()
      reject(new Error('Unable to establish analysis stream'))
    }
    const handleOpen = () => {
      cleanup()
      resolve()
    }
    const cleanup = () => {
      socket.removeEventListener('open', handleOpen)
      socket.removeEventListener('error', handleError)
    }
    socket.addEventListener('open', handleOpen)
    socket.addEventListener('error', handleError)
  })

  const queue: AnalysisStreamEvent[] = []
  let notify: (() => void) | null = null
  let closed = false

  socket.addEventListener('message', (event) => {
    try {
      const raw = JSON.parse(event.data)
      const normalized = normalizeEvent(raw)
      if (normalized) {
        queue.push(normalized)
        if (notify) {
          notify()
          notify = null
        }
      }
    } catch {
      // ignore malformed message
    }
  })

  const finalize = () => {
    closed = true
    if (notify) {
      notify()
      notify = null
    }
  }

  socket.addEventListener('close', finalize)
  socket.addEventListener('error', finalize)

  try {
    while (!closed || queue.length > 0) {
      if (!queue.length) {
        await new Promise<void>((resolve) => {
          notify = resolve
        })
        continue
      }
      const event = queue.shift()
      if (event) {
        yield event
      }
    }
  } finally {
    socket.close()
  }
}

export interface ArchiveDetail extends ArchiveEntry {
  stats?: {
    competitors_count: number
    changes_count: number
    has_tenant?: boolean
  }
}

export async function fetchArchiveDetail(archiveId: string): Promise<ArchiveDetail> {
  const response = await fetch(`${API_BASE}/api/archives/${encodeURIComponent(archiveId)}`, {
    headers: {
      ...getAuthHeaders(),
    },
  })

  return handleResponse<ArchiveDetail>(response)
}

export async function deleteArchive(archiveId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/archives/${encodeURIComponent(archiveId)}`, {
    method: 'DELETE',
    headers: {
      ...getAuthHeaders(),
    },
  })
  
  await handleResponse(response)
}

export async function fetchAnalysisProgress(taskId: string): Promise<AnalysisStreamEvent[]> {
  const response = await fetch(`${API_BASE}/api/analyze/${encodeURIComponent(taskId)}/progress`, {
    headers: {
      ...getAuthHeaders(),
    },
  })

  const data = await handleResponse<{ events: unknown[] }>(response)
  return data.events
    .map(normalizeEvent)
    .filter((event): event is AnalysisStreamEvent => Boolean(event))
}

function mapMonitor(raw: Record<string, unknown>): MonitorSummary {
  const trackedCompetitorIds = Array.isArray(raw.tracked_competitor_ids)
    ? (raw.tracked_competitor_ids as unknown[]).map((value) => String(value))
    : []
  const trackedCompetitorSlugs = Array.isArray(raw.tracked_competitor_slugs)
    ? (raw.tracked_competitor_slugs as unknown[]).map((value) => String(value))
    : []

  const nameFromResponse = typeof raw.name === 'string' ? raw.name : ''
  const displayName = typeof raw.display_name === 'string' && raw.display_name.trim()
    ? raw.display_name.trim()
    : nameFromResponse.trim()
  const urlValue = typeof raw.url === 'string' ? raw.url.trim() : ''

  const canonicalUrl = typeof raw.canonical_url === 'string' && raw.canonical_url.trim()
    ? raw.canonical_url.trim()
    : undefined
  const displayDomain = typeof raw.display_domain === 'string' && raw.display_domain.trim()
    ? raw.display_domain.trim()
    : undefined
  const trackedCount = typeof raw.tracked_competitor_count === 'number'
    ? raw.tracked_competitor_count
    : undefined

  return {
    id: String(raw.id ?? ''),
    name: displayName || nameFromResponse,
    displayName: displayName || undefined,
    displayDomain,
    canonicalUrl,
    url: urlValue,
    createdAt: String(raw.created_at ?? new Date().toISOString()),
    updatedAt: (raw.updated_at as string | null | undefined) ?? null,
    lastRunAt: (raw.last_run_at as string | null | undefined) ?? null,
    latestTaskId: (raw.latest_task_id as string | null | undefined) ?? null,
    latestTaskStatus: (raw.latest_task_status as string | null | undefined) ?? null,
    latestTaskProgress: typeof raw.latest_task_progress === 'number' ? raw.latest_task_progress : null,
    archivedAt: (raw.archived_at as string | null | undefined) ?? null,
    trackedCompetitorIds,
    trackedCompetitorSlugs,
    trackedCompetitorCount: trackedCount ?? trackedCompetitorIds.length,
    hasTenant: typeof raw.has_tenant === 'boolean' ? raw.has_tenant : undefined,
  }
}

function mapArchive(raw: Record<string, unknown>): ArchiveEntry {
  return {
    id: String(raw.id ?? ''),
    title: String(raw.title ?? ''),
    monitorId: raw.monitor_id ? String(raw.monitor_id) : null,
    taskId: raw.task_id ? String(raw.task_id) : null,
    createdAt: String(raw.created_at ?? new Date().toISOString()),
    tenant: raw.tenant ?? null,
    competitors: raw.competitors ?? null,
    changes: raw.changes ?? null,
    metadata: (raw.metadata as Record<string, unknown> | null | undefined) ?? null,
  }
}

function buildWebSocketUrl(path: string, token?: string): string {
  const base = new URL(API_BASE)
  const protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
  const target = new URL(path, base)
  target.protocol = protocol
  if (token) {
    target.searchParams.set('token', token)
  }
  return target.toString()
}

function normalizeEvent(payload: unknown): AnalysisStreamEvent | null {
  if (!payload || typeof payload !== 'object') {
    return null
  }
  const record = payload as Record<string, unknown>
  const type = typeof record.type === 'string' ? (record.type as string) : 'stage'
  const stageValue = typeof record.stage === 'string' ? record.stage : undefined
  const progress = typeof record.progress === 'number' ? record.progress : undefined

  if (type === 'stage' && (stageValue === 'tenant' || stageValue === 'competitors' || stageValue === 'changes')) {
    return {
      type: 'stage',
      stage: stageValue,
      data: record.data,
      progress,
    }
  }

  return {
    type: 'status',
    stage: stageValue ?? 'unknown',
    progress,
    message: typeof record.message === 'string' ? record.message : undefined,
    data: record.data,
  }
}

function mapTrackedCompetitor(raw: Record<string, unknown>): TrackedCompetitor {
  return {
    id: coalesceString(raw.id, ''),
    competitorId: typeof raw.competitor_id === 'string' ? raw.competitor_id : null,
    displayName: coalesceString(raw.display_name, 'Unnamed competitor'),
    primaryUrl: coalesceUrl(raw.primary_url),
    briefDescription: coalesceString(raw.brief_description, ''),
    source: coalesceString(raw.source, 'analysis'),
    demographics: coalesceString(raw.demographics, ''),
    confidence: typeof raw.confidence === 'number'
      ? clamp(raw.confidence, 0, 1)
      : undefined,
  }
}

function coalesceString(value: unknown, fallback: string): string {
  if (typeof value === 'string' && value.trim()) {
    return value.trim()
  }
  return fallback
}

function coalesceUrl(value: unknown): string {
  const raw = coalesceString(value, 'https://example.com')
  if (raw.startsWith('http://') || raw.startsWith('https://')) {
    return raw
  }
  return `https://${raw.replace(/^\/+/, '')}`
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}
