export type Stage = 'tenant' | 'competitors' | 'changes'

export interface StageEvent<T = unknown> {
  stage: Stage
  data: T
}

interface TenantRecord {
  tenant_id?: string
  tenant_url?: string
  tenant_name?: string
  tenant_description?: string
  target_market?: string
  key_features?: string[]
}

interface TenantSummary {
  tenant_id: string
  tenant_url: string
  tenant_name: string
  tenant_description: string
  target_market: string
  key_features: string[]
}

interface CompetitorRecord {
  id?: string
  display_name?: string
  primary_url?: string
  brief_description?: string
  source?: string
  confidence?: number
  demographics?: string
  target_users?: string
  name?: string
  url?: string
  description?: string
}

interface CompetitorSummary {
  id: string
  display_name: string
  primary_url: string
  brief_description: string
  source: string
  confidence: number
  demographics: string
}

interface CompetitorsSummaryPayload {
  competitors: CompetitorSummary[]
}

interface ChangeDetail {
  id?: string
  url: string
  change_type: string
  content: string
  timestamp: string
  threat_level: number
  why_matter: string
  suggestions: string
  read_at?: string | null
}

interface ChangesSummaryPayload {
  changes: ChangeDetail[]
}

interface BackendChangeEntry {
  id?: string
  change_type?: string
  content?: string
  timestamp?: string
  threat_level?: number
  why_matter?: string
  suggestions?: string
  read_at?: string | null
}

interface CompetitorChangeEnvelope {
  changes?: BackendChangeEntry[]
}

interface CompetitorAnalysisEntry {
  competitor?: CompetitorRecord
  changes?: CompetitorChangeEnvelope
}

type CompetitorAnalysisMap = Record<string, CompetitorAnalysisEntry>


// 你现有的API请求类型
interface AnalysisRequest {
  company_name: string
  enable_research: boolean
  max_competitors: number
  enable_caching: boolean
}

interface TaskResponse {
  task_id: string
  message: string
}

interface StatusResponse {
  task_id: string
  status: string
  progress: number
  message: string
  company_name: string
}

interface TaskResults {
  task_id: string
  status: string
  results: {
    tenant?: TenantRecord | null
    competitors?: CompetitorRecord[] | null
    competitor_analysis?: CompetitorAnalysisMap | null
    summary?: unknown
  }
  started_at: string
  completed_at: string
}

// 数据格式转换函数
function transformTenantData(tenant: TenantRecord | null | undefined): TenantSummary {
  const rawFeatures = tenant?.key_features
  const keyFeatures = Array.isArray(rawFeatures) ? rawFeatures : []

  return {
    tenant_id: tenant?.tenant_id ?? 'unknown',
    tenant_url: tenant?.tenant_url ?? 'unknown',
    tenant_name: tenant?.tenant_name ?? 'Unknown Company',
    tenant_description: tenant?.tenant_description ?? 'Unknown description',
    target_market: tenant?.target_market ?? 'Unknown market',
    key_features: keyFeatures,
  }
}

function transformCompetitorsData(competitors: CompetitorRecord[] | null | undefined): CompetitorsSummaryPayload {
  const list = competitors ?? []
  return {
    competitors: list.map((comp, index) => ({
      id: comp.id ?? `comp_${index}`,
      display_name: comp.display_name ?? comp.name ?? 'Unknown Competitor',
      primary_url: comp.primary_url ?? comp.url ?? '',
      brief_description: comp.brief_description ?? comp.description ?? 'No description available',
      source: comp.source ?? 'search',
      confidence: typeof comp.confidence === 'number' ? comp.confidence : 0.5,
      demographics: comp.demographics ?? comp.target_users ?? 'Unknown demographics',
    })),
  }
}

function transformChangesData(
  competitorAnalysis: CompetitorAnalysisMap | null | undefined,
  competitors: CompetitorRecord[] | null | undefined
): ChangesSummaryPayload {
  const analysisEntries: CompetitorAnalysisEntry[] = Object.values(competitorAnalysis ?? {})
  const firstWithChanges = analysisEntries.find((analysis) => {
    const changeList = analysis?.changes?.changes
    return Array.isArray(changeList) && changeList.length > 0
  })

  if (firstWithChanges?.competitor) {
    const fallbackUrl = firstWithChanges.competitor.primary_url ?? 'Unknown URL'
    const rawChanges = firstWithChanges.changes?.changes ?? []
    const normalized: ChangeDetail[] = rawChanges.map((change, index) => {
      const threatLevel = typeof change?.threat_level === 'number' ? change.threat_level : 5

      return {
        id: change?.id ?? `${fallbackUrl}-change-${index}`,
        url: fallbackUrl,
        change_type: change?.change_type ?? 'Modified',
        content: change?.content ?? 'No content available',
        timestamp: change?.timestamp ?? new Date().toISOString(),
        threat_level: threatLevel,
        why_matter: change?.why_matter ?? 'Impact assessment pending',
        suggestions: change?.suggestions ?? 'No suggestions available',
        read_at: change?.read_at ?? null,
      }
    })

    return { changes: normalized }
  }

  const firstComp = (competitors ?? [])[0]
  const fallbackUrl = firstComp?.primary_url ?? 'Unknown URL'
  return {
    changes: [
      {
        id: `${fallbackUrl}-baseline`,
        url: fallbackUrl,
        change_type: 'Analysis',
        content: 'Competitor analysis completed',
        timestamp: new Date().toISOString(),
        threat_level: 3,
        why_matter: 'Baseline competitor intelligence gathered',
        suggestions: 'Continue monitoring for future changes',
        read_at: null,
      },
    ],
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function extractCompanyName(targetUrl: string): string {
  let companyName = 'example-company'

  const urlParts = targetUrl.split('?')
  if (urlParts.length > 1) {
    const params = new URLSearchParams(urlParts[1])
    const company = params.get('company')
    if (company) {
      companyName = decodeURIComponent(company)
    }
  }

  return companyName
    .replace(/^https?:\/\//, '')
    .replace(/^www\./, '')
    .replace(/\/$/, '')
    .split('/')[0]
}

// 主要的流式API函数 - 默认使用前端内置Mock，必要时可切换回后端
export async function* streamMockRun(url: string): AsyncGenerator<StageEvent, void, unknown> {
  const companyName = extractCompanyName(url)
  const shouldUseBackend = (import.meta.env.VITE_USE_BACKEND ?? '').toLowerCase() === 'true'

  if (shouldUseBackend) {
    yield* streamBackendRun(url, companyName)
    return
  }

  yield* streamDesignMock(companyName)
}

async function* streamBackendRun(_originalUrl: string, companyName: string): AsyncGenerator<StageEvent, void, unknown> {
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

  try {
    // 第1步：开始分析
    const analysisRequest: AnalysisRequest = {
      company_name: companyName,
      enable_research: true,
      max_competitors: 10,
      enable_caching: true
    }

    const startResponse = await fetch(`${base}/api/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(analysisRequest)
    })

    if (!startResponse.ok) {
      throw new Error(`Failed to start analysis: ${startResponse.statusText}`)
    }

    const taskData: TaskResponse = await startResponse.json()
    const taskId = taskData.task_id

    // 第2步：轮询状态并模拟流式响应
    let tenantSent = false
    let competitorsSent = false
    let changesSent = false

    while (true) {
      // 获取当前状态
      const statusResponse = await fetch(`${base}/api/status/${taskId}`)
      if (!statusResponse.ok) {
        throw new Error(`Failed to get status: ${statusResponse.statusText}`)
      }

      const status: StatusResponse = await statusResponse.json()
      
      // 根据进度发送不同阶段的数据
      if (!tenantSent && status.progress >= 25) {
        // 发送租户信息（模拟数据，因为状态API可能不包含具体数据）
        yield {
          stage: 'tenant',
          data: {
            tenant_id: companyName.toLowerCase().replace(/[^a-z0-9]/g, '_'),
            tenant_url: `https://${companyName.replace(/[^a-zA-Z0-9]/g, '')}.com`,
            tenant_name: companyName.charAt(0).toUpperCase() + companyName.slice(1),
            tenant_description: `${companyName} company analysis`,
            target_market: 'Market analysis in progress',
            key_features: ['Feature analysis', 'Competitive intelligence', 'Market positioning']
          }
        }
        tenantSent = true
        await sleep(1000) // 模拟延迟
      }

      if (!competitorsSent && status.progress >= 75) {
        // 发送竞争对手信息（模拟数据）
        yield {
          stage: 'competitors',
          data: {
            competitors: [
              {
                id: 'competitor_1',
                display_name: 'Competitor Analysis',
                primary_url: 'https://competitor1.com',
                brief_description: 'Competitive analysis in progress',
                source: 'search',
                confidence: 0.8,
                demographics: 'Analysis pending'
              }
            ]
          }
        }
        competitorsSent = true
        await sleep(1000)
      }

      // 检查任务是否完成
      if (status.status === 'completed') {
        // 获取最终结果
        const resultsResponse = await fetch(`${base}/api/results/${taskId}`)
        if (resultsResponse.ok) {
          const results: TaskResults = await resultsResponse.json()
          
          // 重新发送真实的租户数据（如果有）
          if (results.results.tenant) {
            yield {
              stage: 'tenant',
              data: transformTenantData(results.results.tenant)
            }
          }

          // 重新发送真实的竞争对手数据
          if (results.results.competitors && results.results.competitors.length > 0) {
            yield {
              stage: 'competitors',
              data: transformCompetitorsData(results.results.competitors)
            }
          }

          // 发送变化检测数据
          if (!changesSent) {
            yield {
              stage: 'changes',
              data: transformChangesData(
                results.results.competitor_analysis,
                results.results.competitors ?? []
              )
            }
            changesSent = true
          }
        }
        break
      }

      if (status.status === 'failed') {
        throw new Error(`Analysis failed: ${status.message}`)
      }

      await sleep(2000) // 每2秒轮询一次
    }

  } catch (error) {
    console.error('Analysis error:', error)
    throw error
  }
}

async function* streamDesignMock(companyName: string): AsyncGenerator<StageEvent, void, unknown> {
  const cleanName = companyName || 'example-company'
  const readableName = cleanName
    .split('.')[0]
    .replace(/[-_]/g, ' ')
  const titleCaseName = readableName.charAt(0).toUpperCase() + readableName.slice(1)

  const tenantPayload: TenantSummary = {
    tenant_id: cleanName.toLowerCase().replace(/[^a-z0-9]/g, '_') || 'example_company',
    tenant_url: `https://${cleanName}`,
    tenant_name: titleCaseName || 'Example Company',
    tenant_description: `${titleCaseName} helps modern teams orchestrate product launches with autonomous competitive intelligence.`,
    target_market: 'B2B SaaS · Growth-stage teams',
    key_features: ['Automated monitoring', 'Competitor diffing', 'Narrative-ready briefs']
  }

  const competitorsPayload: CompetitorsSummaryPayload = {
    competitors: [
      {
        id: 'crayon.co',
        display_name: 'Crayon',
        primary_url: 'https://www.crayon.co',
        brief_description: 'Enterprise platform for competitive intelligence battlecards and enablement.',
        source: 'search',
        confidence: 0.84,
        demographics: 'Product marketing and enablement teams'
      },
      {
        id: 'klue.com',
        display_name: 'Klue',
        primary_url: 'https://klue.com',
        brief_description: 'Competitive intelligence hub that centralizes insights for revenue teams.',
        source: 'search',
        confidence: 0.81,
        demographics: 'Mid-market to enterprise GTM orgs'
      },
      {
        id: 'contify.com',
        display_name: 'Contify',
        primary_url: 'https://www.contify.com',
        brief_description: 'Market and competitor intelligence platform with curated news feeds.',
        source: 'search',
        confidence: 0.77,
        demographics: 'Market intelligence and strategy teams'
      },
      {
        id: 'kompyte.com',
        display_name: 'Kompyte',
        primary_url: 'https://www.kompyte.com',
        brief_description: 'Automates competitor monitoring to keep battlecards and messaging current.',
        source: 'search',
        confidence: 0.74,
        demographics: 'Product marketing and sales enablement'
      },
      {
        id: 'similarweb.com',
        display_name: 'Similarweb',
        primary_url: 'https://www.similarweb.com',
        brief_description: 'Digital intelligence suite tracking web traffic, acquisition, and market share.',
        source: 'search',
        confidence: 0.7,
        demographics: 'Growth, strategy, and analyst teams'
      }
    ]
  }

  const changesPayloads: Array<{ url: string; changes: Array<Omit<ChangeDetail, 'url'>> }> = [
    {
      url: 'https://signalforge.io/changelog/march',
      changes: [
        {
          id: 'signalforge-1',
          change_type: 'Added',
          content: 'Launched “Signals Remix” – auto-generated competitive briefs from raw change logs.',
          timestamp: new Date().toISOString(),
          threat_level: 7,
          why_matter: 'Directly overlaps with opp’s narrative summaries; expect higher deal pressure with ops teams.',
          suggestions: 'Highlight opp’s multi-source ingestion and schedule demo blitz for active SignalForge overlaps.',
          read_at: null,
        },
        {
          id: 'signalforge-2',
          change_type: 'Deleted',
          content: 'Introduced usage-based tier starting at $59 seat/month for startups.',
          timestamp: new Date().toISOString(),
          threat_level: 5,
          why_matter: 'Undercuts our entry plan—early-stage prospects may churn unless value gaps are explicit.',
          suggestions: 'Bundle opp’s monitoring with advisory hours for seed companies; refresh comparison deck.',
          read_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
        },
        {
          id: 'signalforge-3',
          change_type: 'Modified',
          content: 'Retired the legacy weekly PDF digest in favor of in-app digests.',
          timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
          threat_level: 3,
          why_matter: 'Signals stronger product focus on real-time experiences; lowers pressure for traditional brief formats.',
          suggestions: 'Lean into our cross-channel export options for teams still needing static PDFs.',
          read_at: null,
        }
      ]
    },
    {
      url: 'https://glyphhq.com/blog/new-pricing',
      changes: [
        {
          id: 'glyph-1',
          change_type: 'Modified',
          content: 'Homepage headline now positions Glyph HQ as “Autonomous GTM intelligence for product marketers”.',
          timestamp: new Date().toISOString(),
          threat_level: 6,
          why_matter: 'Signals a narrative shift directly into opp’s value prop; expect more overlap in evaluation cycles.',
          suggestions: 'Ship updated pitch slides contrasting opp’s data coverage and human-in-the-loop briefings.',
          read_at: null,
        },
        {
          id: 'glyph-2',
          change_type: 'Added',
          content: 'Released Chrome extension that snapshots competitor pricing pages weekly.',
          timestamp: new Date().toISOString(),
          threat_level: 4,
          why_matter: 'Feature parity with opp’s scheduled monitors could dilute differentiation in SMB deals.',
          suggestions: 'Highlight opp’s multi-source enrichment and roll out our own pricing monitor recipe for reps.',
          read_at: null,
        },
        {
          id: 'glyph-3',
          change_type: 'Added',
          content: 'Introduced Slack digest summarising top three detected changes per workspace daily.',
          timestamp: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
          threat_level: 5,
          why_matter: 'Raises expectations for native collaboration touchpoints that opp must match or exceed.',
          suggestions: 'Prioritise our Slack workflow beta announcement in upcoming nurture emails.',
          read_at: null,
        }
      ]
    },
    {
      url: 'https://www.kompyte.com/product-updates',
      changes: [
        {
          id: 'kompyte-1',
          change_type: 'Added',
          content: 'Shipped AI-generated battlecard summaries targeting enterprise sellers.',
          timestamp: new Date().toISOString(),
          threat_level: 8,
          why_matter: 'Directly competes with opp’s differentiator; expect elevated enterprise bake-off frequency.',
          suggestions: 'Accelerate case-study refreshes highlighting opp’s human QA loop on AI summaries.',
          read_at: null,
        },
        {
          id: 'kompyte-2',
          change_type: 'Modified',
          content: 'Published benchmark report citing 22% faster win/loss response times with Kompyte.',
          timestamp: new Date(Date.now() - 1000 * 60 * 240).toISOString(),
          threat_level: 6,
          why_matter: 'Arms sales teams with fresh ROI proof that may appear in competitive deals.',
          suggestions: 'Prepare counter-narrative with our customer time-to-insight metrics and executive quotes.',
          read_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
        },
        {
          id: 'kompyte-3',
          change_type: 'Deleted',
          content: 'Deprecated Salesforce integration tier for Starter plans.',
          timestamp: new Date(Date.now() - 1000 * 60 * 360).toISOString(),
          threat_level: 4,
          why_matter: 'Opens positioning gap for SMB teams needing native CRM sync— opportunity for opp to lean in.',
          suggestions: 'Promote opp’s plug-and-play CRM connectors in outbound messaging to SMB pipeline.',
          read_at: null,
        }
      ]
    }
  ]

  await sleep(3000)
  yield { stage: 'tenant', data: tenantPayload }

  await sleep(3000)
  yield { stage: 'competitors', data: competitorsPayload }

  const combinedChangesPayload: ChangesSummaryPayload = {
    changes: changesPayloads.flatMap((payload) =>
      payload.changes.map<ChangeDetail>((change, index) => ({
        id: change.id ?? `${payload.url}-change-${index}`,
        url: payload.url,
        change_type: change.change_type,
        content: change.content,
        timestamp: change.timestamp,
        threat_level: change.threat_level,
        why_matter: change.why_matter,
        suggestions: change.suggestions,
        read_at: change.read_at ?? null,
      }))
    )
  }

  await sleep(3000)
  yield { stage: 'changes', data: combinedChangesPayload }
}

// 保持原有函数作为备用（如果需要直接调用流式mock API）
export async function* streamOriginalMockRun(url: string): AsyncGenerator<StageEvent, void, unknown> {
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
  const target = url.startsWith('http') ? url : `${base}${url}`
  const response = await fetch(target)
  if (!response.body) throw new Error('No response body')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let newlineIndex
    while ((newlineIndex = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newlineIndex).trim()
      buffer = buffer.slice(newlineIndex + 1)
      if (!line) continue
      yield JSON.parse(line)
    }
  }

  if (buffer.trim()) {
    yield JSON.parse(buffer)
  }
}
