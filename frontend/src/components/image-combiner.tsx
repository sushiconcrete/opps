"use client"

import { useEffect, useState, useRef, useCallback, type Dispatch, type SetStateAction, type ReactNode } from "react"

import { AnimatedBackground } from "@/components/animated-background"
import ExpandableCard, { type CardItem } from "@/components/forgeui/expandable-card"
import { Button } from "@/components/ui/button"
import { Scrollspy } from "@/components/ui/scrollspy"
import { Input } from "@/components/ui/input"
import { TypingText } from "@/components/ui/typing-text"
import { Slider } from "@/components/ui/slider"
import {
  startAnalysis,
  streamAnalysisEvents,
  fetchMonitors,
  createMonitor as apiCreateMonitor,
  deleteMonitor as apiDeleteMonitor,
  updateMonitorName as apiUpdateMonitorName,
  fetchAnalysisProgress,
  markChangeRead as apiMarkChangeRead,
  bulkMarkChangesRead as apiBulkMarkChangesRead,
  trackCompetitor as apiTrackCompetitor,
  untrackCompetitor as apiUntrackCompetitor,
  fetchArchives,
  createArchive,
  adaptTenantStage,
  adaptCompetitorStage,
  adaptChangeStage,
  type AnalysisStreamEvent,
  type MonitorSummary,
  type ArchiveEntry,
  type TenantSnapshot,
  type ChangeInsight,
  type TrackedCompetitor,
  type CompetitorInsight,
} from "@/utils/api"
import { TextShimmer } from "@/components/motion-primitives/text-shimmer"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ModeToggle } from "@/components/mode-toggle"
import { ChevronDown, Edit3, Plus, Trash2 } from "lucide-react"
type InlineEditProps = {
  value: string
  onSave: (newValue: string) => void
  onCancel: () => void
  className?: string
  maxLength?: number
  isEditing: boolean
  getBoundaryElement?: () => HTMLElement | null
}

function InlineEdit({
  value,
  onSave,
  onCancel,
  className = "",
  maxLength = 30,
  isEditing,
  getBoundaryElement,
}: InlineEditProps) {
  const [editValue, setEditValue] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing, value])

  useEffect(() => {
    setEditValue(value)
  }, [value])

  const handleSave = () => {
    const trimmedValue = editValue.trim()
    if (trimmedValue && trimmedValue !== value) {
      onSave(trimmedValue)
    } else {
      onCancel()
    }
  }

  const handleCancel = () => {
    setEditValue(value)
    onCancel()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation()
    if ('nativeEvent' in e && typeof e.nativeEvent.stopImmediatePropagation === 'function') {
      e.nativeEvent.stopImmediatePropagation()
    }

    if (e.key === 'Enter') {
      e.preventDefault()
      handleSave()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      handleCancel()
    }
  }

  const shouldKeepEditing = (candidate: EventTarget | null): candidate is Node => {
    if (!candidate || !(candidate instanceof Node)) return false
    if (!containerRef.current) return false

    if (containerRef.current.contains(candidate)) return true

    const parent = containerRef.current.parentElement
    if (parent?.contains(candidate)) return true

    const boundary = getBoundaryElement?.()
    return !!boundary && boundary.contains(candidate)
  }

  const refocusInput = () => {
    requestAnimationFrame(() => {
      if (isEditing) {
        inputRef.current?.focus()
      }
    })
  }

  const handleBlur = (event: React.FocusEvent<HTMLInputElement>) => {
    if (shouldKeepEditing(event.relatedTarget)) {
      refocusInput()
      return
    }

    requestAnimationFrame(() => {
      const activeElement = document.activeElement

      if (shouldKeepEditing(activeElement)) {
        refocusInput()
        return
      }

      if (activeElement !== inputRef.current) {
        handleSave()
      }
    })
  }

  if (isEditing) {
    return (
      <div ref={containerRef} className="w-full">
        <input
          ref={inputRef}
          type="text"
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          className={`w-full border-none bg-transparent text-sm font-medium text-foreground outline-none placeholder:text-muted-foreground focus:outline-none focus:ring-0 ${className}`}
        />
      </div>
    )
  }

  const truncatedValue = value.length > maxLength ? `${value.slice(0, maxLength)}...` : value

  return (
    <span
      className={`truncate text-sm font-medium text-foreground ${className}`}
      title={value.length > maxLength ? value : undefined}
    >
      {truncatedValue}
    </span>
  )
}

const audience = ["solo founders", "lean startups", "indie operators"]

type ChangeRadarEntry = ChangeInsight
type Monitor = MonitorSummary
type ArchiveItem = ArchiveEntry
type ImageCombinerProps = {
  onRequestAuth: () => void
  isAuthenticated?: boolean
}

export function ImageCombiner({ onRequestAuth, isAuthenticated = false }: ImageCombinerProps) {
  const [url, setUrl] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<"form" | "results">(() => "form")
  const [activeCompany, setActiveCompany] = useState<string | null>(null)
  const [tenant, setTenant] = useState<TenantSnapshot | null>(null)
  const [competitorCards, setCompetitorCards] = useState<CardItem[]>([])
  const [changes, setChanges] = useState<ChangeRadarEntry[]>([])
  const [resultsSession, setResultsSession] = useState(0)
  const [monitors, setMonitors] = useState<Monitor[]>([])
  const [currentMonitorId, setCurrentMonitorId] = useState<string | null>(null)
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [isLoadingMonitorResults, setIsLoadingMonitorResults] = useState(false)
  const [trackedCompetitorIds, setTrackedCompetitorIds] = useState<string[]>([])
  const [hasMonitorAccess, setHasMonitorAccess] = useState(false)
  const [archives, setArchives] = useState<ArchiveItem[]>([])
  const [archivesLoading, setArchivesLoading] = useState(false)
  const [isBulkMarkPending, setIsBulkMarkPending] = useState(false)
  const [isMonitorCreateOpen, setIsMonitorCreateOpen] = useState(false)
  const [isCreatingMonitor, setIsCreatingMonitor] = useState(false)
  const [monitorForm, setMonitorForm] = useState({ url: '', name: '' })

  const streamRef = useRef<{ cancel: () => void } | null>(null)
  const currentMonitorIdRef = useRef<string | null>(null)
  const activeTaskIdRef = useRef<string | null>(null)
  const loadMonitorsPromiseRef = useRef<Promise<void> | null>(null)
  const loadArchivesPromiseRef = useRef<Promise<void> | null>(null)

  useEffect(() => {
    currentMonitorIdRef.current = currentMonitorId
  }, [currentMonitorId])

  useEffect(() => {
    activeTaskIdRef.current = activeTaskId
  }, [activeTaskId])

  const isAuthError = useCallback((error: unknown): boolean => {
    if (!(error instanceof Error)) {
      return false
    }
    const message = error.message.toLowerCase()
    return (
      message.includes('unauthorized') ||
      message.includes('authentication') ||
      message.includes('forbidden')
    )
  }, [])

  const convertMonitor = useCallback((summary: MonitorSummary): Monitor => {
    const displayName = summary.displayName?.trim() || summary.name
    const displayDomain = summary.displayDomain?.trim() || summary.displayDomain
    const canonicalUrl = summary.canonicalUrl?.trim() || summary.canonicalUrl

    return {
      ...summary,
      name: displayName,
      displayName,
      displayDomain: displayDomain || undefined,
      canonicalUrl: canonicalUrl || undefined,
      trackedCompetitorIds: [...summary.trackedCompetitorIds],
      trackedCompetitorSlugs: [...summary.trackedCompetitorSlugs],
      trackedCompetitorCount:
        typeof summary.trackedCompetitorCount === 'number'
          ? summary.trackedCompetitorCount
          : summary.trackedCompetitorIds.length,
    }
  }, [])

  const loadMonitorResults = useCallback(async (taskId?: string | null) => {
    if (!taskId) {
      setActiveTaskId(null)
      setTenant(null)
      setCompetitorCards([])
      setChanges([])
      setTrackedCompetitorIds([])
      return
    }

    setIsLoadingMonitorResults(true)
    try {
      const events = await fetchAnalysisProgress(taskId)
      const tenantEvent = events.find((event) => event.type === 'stage' && event.stage === 'tenant')
      if (tenantEvent?.type === 'stage') {
        const snapshot = adaptTenantStage(tenantEvent.data)
        setTenant(snapshot)
      } else {
        setTenant(null)
      }

      const competitorsEvent = events.find((event) => event.type === 'stage' && event.stage === 'competitors')
      if (competitorsEvent?.type === 'stage') {
        const snapshot = adaptCompetitorStage(competitorsEvent.data)
        const trackedSet = new Set(snapshot.trackedCompetitorIds)
        const cards = snapshot.competitors.map((insight) =>
          toCompetitorCard(
            insight,
            trackedSet.size === 0
              ? true
              : trackedSet.has(insight.id) || (insight.competitorId ? trackedSet.has(insight.competitorId) : false),
          )
        )
        setCompetitorCards(cards)

        const trackedFromStage = snapshot.trackedCompetitorIds.length
          ? snapshot.trackedCompetitorIds
          : cards.map((card) => card.id)
        setTrackedCompetitorIds(trackedFromStage)
      } else {
        setCompetitorCards([])
        setTrackedCompetitorIds([])
      }

      const changesEvent = events.find((event) => event.type === 'stage' && event.stage === 'changes')
      if (changesEvent?.type === 'stage') {
        const radar = adaptChangeStage(changesEvent.data)
        setChanges((previous) => mergeChangeReadState(previous, radar))
      } else {
        setChanges([])
      }

      setActiveTaskId(taskId)
    } catch (err) {
      console.error('Failed to load monitor results', err)
      setError(err instanceof Error ? err.message : 'Unable to load monitor results')
    } finally {
      setIsLoadingMonitorResults(false)
    }
  }, [])

  const loadMonitors = useCallback(async () => {
    if (loadMonitorsPromiseRef.current) {
      return loadMonitorsPromiseRef.current
    }

    const request = (async () => {
      try {
        const summaries = await fetchMonitors()
        const mapped = summaries.map(convertMonitor)
        setMonitors(mapped)
        setHasMonitorAccess(true)

        if (mapped.length === 0) {
          if (!streamRef.current) {
            setView((previous) => (previous === 'results' ? 'form' : previous))
          }
          if (currentMonitorIdRef.current !== null) {
            setCurrentMonitorId(null)
          }
          if (activeTaskIdRef.current !== null) {
            setActiveTaskId(null)
          }
          setTenant(null)
          setCompetitorCards([])
          setChanges([])
          setTrackedCompetitorIds([])
          return
        }

        const previousMonitorId = currentMonitorIdRef.current
        const preferred = previousMonitorId
          ? mapped.find((monitor) => monitor.id === previousMonitorId) ?? mapped[0]
          : mapped[0]

        if (!preferred) {
          return
        }

        if (preferred.id !== previousMonitorId) {
          setCurrentMonitorId(preferred.id)
        }

        const nextCompany = preferred.canonicalUrl ?? preferred.url ?? null
        setActiveCompany((current) => (current === nextCompany ? current : nextCompany))

        setTrackedCompetitorIds((current) =>
          arraysEqual(current, preferred.trackedCompetitorIds) ? current : preferred.trackedCompetitorIds,
        )

        const latestTaskId = preferred.latestTaskId ?? null
        if (latestTaskId) {
          const shouldReloadResults = streamRef.current !== null || latestTaskId !== activeTaskIdRef.current
          setActiveTaskId(latestTaskId)
          if (shouldReloadResults) {
            await loadMonitorResults(latestTaskId)
          }
          setView((previous) => (previous === 'results' ? previous : 'results'))
        } else if (!streamRef.current) {
          if (activeTaskIdRef.current !== null) {
            setActiveTaskId(null)
          }
          setTenant(null)
          setCompetitorCards([])
          setChanges([])
          setView((previous) => (previous === 'results' ? previous : 'results'))
        }
      } catch (err) {
        console.error('Failed to load monitors', err)
        if (isAuthError(err)) {
          setHasMonitorAccess(false)
        }
        setError(err instanceof Error ? err.message : 'Unable to load monitors')
      }
    })()

    loadMonitorsPromiseRef.current = request
    try {
      await request
    } finally {
      loadMonitorsPromiseRef.current = null
    }
  }, [convertMonitor, loadMonitorResults, isAuthError])

  const loadArchives = useCallback(async () => {
    if (loadArchivesPromiseRef.current) {
      return loadArchivesPromiseRef.current
    }

    const request = (async () => {
      setArchivesLoading(true)
      try {
        const items = await fetchArchives()
        setArchives(items)
      } catch (err) {
        console.error('Failed to load archives', err)
      } finally {
        setArchivesLoading(false)
      }
    })()

    loadArchivesPromiseRef.current = request
    try {
      await request
    } finally {
      loadArchivesPromiseRef.current = null
    }
  }, [])

  const handlePrimaryCtaClick = useCallback(() => {
    if (!isAuthenticated) {
      onRequestAuth()
      return
    }
    setView('results')
    void loadMonitors()
    void loadArchives()
  }, [isAuthenticated, onRequestAuth, loadArchives, loadMonitors])

  useEffect(() => {
    loadMonitors()
    loadArchives()
  }, [loadMonitors, loadArchives])

  useEffect(() => {
    if (!isAuthenticated) {
      setHasMonitorAccess(false)
    }
  }, [isAuthenticated])

  // After successful authentication, refresh monitors/archives to decide view
  useEffect(() => {
    if (isAuthenticated) {
      // Optimistically show dashboard; if no monitors, loadMonitors will revert to form
      setView('results')
      loadMonitors()
      loadArchives()
    }
  }, [isAuthenticated, loadMonitors, loadArchives])

  useEffect(() => {
    if (!isAuthenticated) {
      setView("form")
    }
  }, [isAuthenticated])

  const handleUrlChange = (value: string) => {
    setUrl(value.replace(/^https?:\/\//i, ""))
  }

  const handleDeleteMonitor = async (monitorId: string) => {
    try {
      await apiDeleteMonitor(monitorId)
      if (currentMonitorId === monitorId) {
        streamRef.current?.cancel()
        setCurrentMonitorId(null)
        setActiveTaskId(null)
        setTenant(null)
        setCompetitorCards([])
        setChanges([])
        setTrackedCompetitorIds([])
      }
      await loadMonitors()
      await loadArchives()
    } catch (err) {
      console.error('Failed to delete monitor', err)
      if (isAuthError(err)) {
        setHasMonitorAccess(false)
      }
      setError(err instanceof Error ? err.message : 'Unable to delete monitor')
    }
  }

  const handleSwitchMonitor = async (monitorId: string) => {
    const monitor = monitors.find((m) => m.id === monitorId)
    if (!monitor) {
      setError('Selected monitor is no longer available')
      return
    }

    streamRef.current?.cancel()
    setCurrentMonitorId(monitorId)
    setActiveCompany(monitor.canonicalUrl ?? monitor.url)
    setTrackedCompetitorIds(monitor.trackedCompetitorIds)
    try {
      await loadMonitorResults(monitor.latestTaskId ?? null)
      setView('results')
    } catch (err) {
      console.error('Failed to switch monitor', err)
      setError(err instanceof Error ? err.message : 'Unable to switch monitor')
    }
  }

  const handleUpdateMonitorName = async (monitorId: string, newName: string) => {
    try {
      const updated = await apiUpdateMonitorName(monitorId, newName)
      const mapped = convertMonitor(updated)
      setMonitors((previous) => previous.map((monitor) => (monitor.id === monitorId ? mapped : monitor)))
      if (currentMonitorId === monitorId) {
        setActiveCompany(mapped.canonicalUrl ?? mapped.url)
      }
      setHasMonitorAccess(true)
    } catch (err) {
      console.error('Failed to update monitor name', err)
      if (isAuthError(err)) {
        setHasMonitorAccess(false)
      }
      setError(err instanceof Error ? err.message : 'Unable to rename monitor')
    }
  }



  const handleMarkChangeRead = async (changeId: string) => {
    try {
      await apiMarkChangeRead(changeId)
    } catch (err) {
      console.error('Failed to mark change read', err)
    }

    setChanges((previous) =>
      previous.map((change) =>
        change.id === changeId && !change.readAt
          ? { ...change, readAt: new Date().toISOString() }
          : change
      )
    )
  }

  const handleBulkMarkChangesRead = async (changeIds: string[]) => {
    if (!changeIds.length || isBulkMarkPending) return
    setIsBulkMarkPending(true)
    try {
      await apiBulkMarkChangesRead(changeIds)
      setChanges((previous) =>
        previous.map((change) =>
          changeIds.includes(change.id) ? { ...change, readAt: new Date().toISOString() } : change
        )
      )
    } catch (err) {
      console.error('Failed to bulk mark changes read', err)
      setError(err instanceof Error ? err.message : 'Unable to mark changes as read')
    } finally {
      setIsBulkMarkPending(false)
    }
  }

  const handleCreateArchive = async () => {
    if (!currentMonitorId || !activeTaskId) {
      setError('Run an analysis before archiving')
      return
    }

    const defaultTitle = `Archive ${new Date().toLocaleString()}`
    const title = typeof window !== 'undefined' ? window.prompt('Archive title', defaultTitle) : defaultTitle
    if (!title) return

    try {
      await createArchive({ monitorId: currentMonitorId, taskId: activeTaskId, title })
      await loadArchives()
    } catch (err) {
      console.error('Failed to archive analysis', err)
      setError(err instanceof Error ? err.message : 'Failed to archive analysis')
    }
  }



  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedUrl = url.trim()
    if (!trimmedUrl) return

    const absoluteUrl = ensureAbsoluteUrl(trimmedUrl)

    // If not authenticated, redirect to login page instead of starting analysis
    if (!isAuthenticated) {
      setHasMonitorAccess(false)
      onRequestAuth()
      setView("form")
      return
    }

    streamRef.current?.cancel()
    setError(null)
    setIsSubmitting(true)
    setIsLoadingMonitorResults(true)
    setActiveCompany(absoluteUrl)
    setResultsSession((session) => session + 1)
    setView("results")
    setTenant(null)
    setCompetitorCards([])
    setChanges([])
    setTrackedCompetitorIds([])

    const normalizedTarget = normalizeMonitorUrl(absoluteUrl)
    const matchedMonitor = monitors.find((monitor) => {
      const candidate = monitor.canonicalUrl ?? monitor.url ?? ""
      return normalizeMonitorUrl(candidate) === normalizedTarget
    })

    setCurrentMonitorId(matchedMonitor ? matchedMonitor.id : null)

    let streamIterator: AsyncIterator<AnalysisStreamEvent> | null = null

    try {
      const { taskId, monitorId } = await startAnalysis(trimmedUrl, {
        monitorId: matchedMonitor?.id,
        tenantUrl: absoluteUrl,
      })

      setActiveTaskId(taskId)

      if (monitorId) {
        const optimisticSummary: MonitorSummary = {
          id: monitorId,
          name:
            matchedMonitor?.displayName ??
            matchedMonitor?.name ??
            toDisplayName(absoluteUrl),
          displayName:
            matchedMonitor?.displayName ?? toDisplayName(absoluteUrl),
          displayDomain:
            matchedMonitor?.displayDomain ?? formatDisplayUrl(absoluteUrl),
          canonicalUrl: matchedMonitor?.canonicalUrl ?? absoluteUrl,
          url: matchedMonitor?.url ?? absoluteUrl,
          createdAt: matchedMonitor?.createdAt ?? new Date().toISOString(),
          updatedAt: matchedMonitor?.updatedAt ?? null,
          lastRunAt: matchedMonitor?.lastRunAt ?? null,
          latestTaskId: taskId,
          latestTaskStatus: 'running',
          latestTaskProgress: 0,
          archivedAt: matchedMonitor?.archivedAt ?? null,
          trackedCompetitorIds: matchedMonitor?.trackedCompetitorIds ?? [],
          trackedCompetitorSlugs: matchedMonitor?.trackedCompetitorSlugs ?? [],
          trackedCompetitorCount: matchedMonitor?.trackedCompetitorCount ?? 0,
          hasTenant: matchedMonitor?.hasTenant,
        }

        const optimisticMonitor = convertMonitor(optimisticSummary)

        setMonitors((previous) => {
          const existing = previous.find((monitor) => monitor.id === monitorId)
          if (!existing) {
            return [optimisticMonitor, ...previous]
          }

          const others = previous.filter((monitor) => monitor.id !== monitorId)
          const merged = {
            ...existing,
            name: optimisticMonitor.name,
            displayName: optimisticMonitor.displayName,
            displayDomain: optimisticMonitor.displayDomain ?? existing.displayDomain,
            canonicalUrl: optimisticMonitor.canonicalUrl ?? existing.canonicalUrl,
            url: optimisticMonitor.url,
            latestTaskId: taskId,
            latestTaskStatus: 'running',
            latestTaskProgress: 0,
          }

          return [merged, ...others]
        })

        setCurrentMonitorId(monitorId)
        setHasMonitorAccess(true)
        setActiveCompany(optimisticMonitor.canonicalUrl ?? optimisticMonitor.url ?? absoluteUrl)
      }

      let cancelled = false
      streamIterator = streamAnalysisEvents(taskId)[Symbol.asyncIterator]()
      streamRef.current = {
        cancel: () => {
          cancelled = true
          if (streamIterator?.return) {
            streamIterator.return().catch(() => undefined)
          }
        },
      }

      while (!cancelled && streamIterator) {
        const { value, done } = await streamIterator.next()
        if (done || cancelled) {
          break
        }
        const event = value

        if (event.type === 'stage') {
          if (event.stage === 'tenant') {
            const snapshot = adaptTenantStage(event.data)
            setTenant(snapshot)
          }
          if (event.stage === 'competitors') {
            const snapshot = adaptCompetitorStage(event.data)
            const trackedSet = new Set(snapshot.trackedCompetitorIds)
            const cards = snapshot.competitors.map((insight) =>
              toCompetitorCard(
                insight,
                trackedSet.size === 0
                  ? true
                  : trackedSet.has(insight.id) || (insight.competitorId ? trackedSet.has(insight.competitorId) : false),
              )
            )
            setCompetitorCards(cards)

            const trackedFromStage = snapshot.trackedCompetitorIds.length
              ? snapshot.trackedCompetitorIds
              : cards.map((card) => card.id)
            setTrackedCompetitorIds(trackedFromStage)
          }
          if (event.stage === 'changes') {
            const radar = adaptChangeStage(event.data)
            setChanges((previous) => {
              return mergeChangeReadState(previous, radar)
            })
          }
        } else if (event.type === 'status') {
          if (event.stage === 'failed') {
            setError(event.message ?? 'Analysis failed')
            break
          }
          if (event.stage === 'complete') {
            setActiveTaskId(taskId)
            await loadMonitors()
            await loadArchives()
            break
          }
        }
      }
    } catch (err) {
      console.error(err)
      setError(err instanceof Error ? err.message : 'Something went wrong while streaming the run.')
    } finally {
      if (streamIterator?.return) {
        try {
          await streamIterator.return()
        } catch {
          // ignore
        }
      }
      setIsSubmitting(false)
      setIsLoadingMonitorResults(false)
      streamRef.current = null
    }
  }

  const handleBackToForm = () => {
    streamRef.current?.cancel()
    streamRef.current = null
    setView("form")
    setError(null)
    setIsSubmitting(false)
    setIsLoadingMonitorResults(false)
    setActiveCompany(null)
    setActiveTaskId(null)
    setTenant(null)
    setCompetitorCards([])
    setChanges([])
    setTrackedCompetitorIds([])
  }

  const handleRequestMonitorCreate = () => {
    // Redirect to landing form to perform a fresh find for the new monitor
    streamRef.current?.cancel()
    setError(null)
    setIsSubmitting(false)
    setIsLoadingMonitorResults(false)
    setActiveCompany(null)
    setActiveTaskId(null)
    setTenant(null)
    setCompetitorCards([])
    setChanges([])
    setTrackedCompetitorIds([])
    setIsMonitorCreateOpen(false)
    setMonitorForm({ url: '', name: '' })
    setView('form')
  }

  const handleMonitorFormSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedUrl = monitorForm.url.trim()
    if (!trimmedUrl) {
      setError('Monitor URL is required')
      return
    }

    setIsCreatingMonitor(true)
    try {
      const absoluteUrl = ensureAbsoluteUrl(trimmedUrl)
      const response = await apiCreateMonitor({
        url: absoluteUrl,
        name: monitorForm.name.trim() || undefined,
      })

      const mapped = convertMonitor(response)
      setMonitors((previous) => {
        const filtered = previous.filter((monitor) => monitor.id !== mapped.id)
        return [mapped, ...filtered]
      })

      setCurrentMonitorId(mapped.id)
      setTrackedCompetitorIds(mapped.trackedCompetitorIds)
      setActiveCompany(mapped.canonicalUrl ?? mapped.url)
      setActiveTaskId(mapped.latestTaskId ?? null)
      setTenant(null)
      setCompetitorCards([])
      setChanges([])
      setHasMonitorAccess(true)

      if (mapped.latestTaskId) {
        await loadMonitorResults(mapped.latestTaskId)
      }

      setView('results')
      setIsMonitorCreateOpen(false)
      setMonitorForm({ url: '', name: '' })
    } catch (err) {
      console.error('Failed to create monitor', err)
      if (isAuthError(err)) {
        setHasMonitorAccess(false)
      }
      setError(err instanceof Error ? err.message : 'Unable to create monitor')
    } finally {
      setIsCreatingMonitor(false)
    }
  }

  return (
    <>
    <div
      className={`relative flex min-h-screen w-full flex-col ${
        view === "form"
          ? "items-center justify-center overflow-y-auto px-6"
          : "justify-start font-roboto"
      }`}
    >
      {view === "form" && (
        <>
          <AnimatedBackground />
          <div className="absolute right-6 top-6 z-20 flex items-center gap-2 sm:gap-3">
            <Button
              type="button"
              onClick={handlePrimaryCtaClick}
              className="h-9 rounded-full bg-gradient-to-br from-[#2563EB] via-[#2563EB] to-[#1D4ED8] px-4 text-sm font-semibold text-white shadow-lg transition hover:from-[#1D4ED8] hover:to-[#1E40AF]"
            >
              {isAuthenticated && hasMonitorAccess ? 'Dashboard' : 'Sign up'}
            </Button>
            <ModeToggle />
          </div>
        </>
      )}

      {view === "form" ? (
        <div className="relative z-10 flex w-full max-w-4xl flex-col items-center gap-6 text-center">
          <LandingContent
            url={url}
            onUrlChange={handleUrlChange}
            isSubmitting={isSubmitting}
            onSubmit={handleSubmit}
            error={error}
          />
        </div>
      ) : (
        <ResultsView
          key={resultsSession}
          companyUrl={activeCompany}
          isSubmitting={isSubmitting}
          isLoadingMonitorResults={isLoadingMonitorResults}
          error={error}
          onBack={handleBackToForm}
          tenant={tenant}
          competitors={competitorCards}
          setCompetitors={setCompetitorCards}
          changes={changes}
          onMarkChangeRead={handleMarkChangeRead}
          onBulkMarkChangesRead={handleBulkMarkChangesRead}
          resetToken={resultsSession}
          monitors={monitors}
          currentMonitorId={currentMonitorId}
          archives={archives}
          archivesLoading={archivesLoading}
          trackedCompetitorIds={trackedCompetitorIds}
          isBulkMarkPending={isBulkMarkPending}
          onCreateArchive={handleCreateArchive}
          onSwitchMonitor={handleSwitchMonitor}
          onDeleteMonitor={handleDeleteMonitor}
          onAddMonitor={handleRequestMonitorCreate}
          onUpdateMonitorName={handleUpdateMonitorName}
          setError={setError}
          setTrackedCompetitorIds={setTrackedCompetitorIds}
        />
      )}
    </div>
      <MonitorCreateDialog
        open={isMonitorCreateOpen}
        isSubmitting={isCreatingMonitor}
        form={monitorForm}
        onOpenChange={(open) => {
          setIsMonitorCreateOpen(open)
          if (!open) {
            setMonitorForm({ url: '', name: '' })
          }
        }}
        onChange={setMonitorForm}
        onSubmit={handleMonitorFormSubmit}
      />
    </>
  )
}

type RunFormProps = {
  url: string
  onUrlChange: (value: string) => void
  isSubmitting: boolean
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
}

function LandingForm({ url, onUrlChange, isSubmitting, onSubmit }: RunFormProps) {
  return (
    <form onSubmit={onSubmit} className="flex w-full flex-col items-center gap-4">
      <div className="flex w-full max-w-2xl flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex w-full items-center gap-2 rounded-lg border border-input bg-card px-3 py-1.5 shadow-sm transition-colors dark:bg-card/60">
          <span className="font-inter text-xs tracking-[0.35em] text-muted-foreground">https://</span>
          <Input
            value={url}
            onChange={(event) => onUrlChange(event.target.value)}
            variant="ghost"
            placeholder="your homepage here"
            className="font-mono text-sm text-foreground focus-visible:ring-0 placeholder:text-muted-foreground h-8 w-full"
            autoComplete="off"
            aria-label="Company URL"
          />
        </div>
        <Button
          type="submit"
          isLoading={isSubmitting}
          loadingText="Scanning..."
          className="h-10 min-w-[5rem] rounded-lg bg-black text-white shadow-sm transition hover:bg-black/90 dark:bg-white dark:text-black dark:hover:bg-white/90"
          disabled={isSubmitting}
        >
          Find
        </Button>
      </div>
    </form>
  )
}

type LandingContentProps = RunFormProps & {
  error: string | null
}

function LandingContent({
  url,
  onUrlChange,
  isSubmitting,
  onSubmit,
  error,
}: LandingContentProps) {
  return (
    <>
      <span className="text-5xl font-mono tracking-[0.35em] text-foreground pl-2">opps_</span>
      <h1 className="flex flex-col text-3xl font-mono text-foreground sm:text-4xl">
        <span>Competitive Intelligence agent for</span>
        <span className="block min-h-[1.5em] text-green-500">
          <TypingText
            texts={audience}
            className="text-green-500"
            speed={90}
            pauseDuration={1600}
            cursor="_"
            cursorClassName="text-green-500"
          />
        </span>
      </h1>
      <p className="max-w-xl text-sm text-muted-foreground">
        Paste a homepage and opp fingerprints competitors, positioning, and live GTM moves in one run.
      </p>

      <LandingForm
        url={url}
        onUrlChange={onUrlChange}
        isSubmitting={isSubmitting}
        onSubmit={onSubmit}
      />

      {error && (
        <p className="max-w-lg rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-left text-xs text-destructive">
          {error}
        </p>
      )}
    </>
  )
}

type ResultsViewProps = {
  companyUrl: string | null
  isSubmitting: boolean
  isLoadingMonitorResults: boolean
  error: string | null
  onBack: () => void
  tenant: TenantSnapshot | null
  competitors: CardItem[]
  setCompetitors: Dispatch<SetStateAction<CardItem[]>>
  changes: ChangeRadarEntry[]
  onMarkChangeRead: (id: string) => void
  onBulkMarkChangesRead: (ids: string[]) => void
  resetToken: number
  monitors: Monitor[]
  currentMonitorId: string | null
  archives: ArchiveItem[]
  archivesLoading: boolean
  trackedCompetitorIds: string[]
  isBulkMarkPending: boolean
  onCreateArchive: () => void
  onSwitchMonitor: (monitorId: string) => void
  onDeleteMonitor: (monitorId: string) => void
  onAddMonitor: () => void
  onUpdateMonitorName: (monitorId: string, newName: string) => void
  setError: (message: string | null) => void
  setTrackedCompetitorIds: Dispatch<SetStateAction<string[]>>
}

function ResultsView({
  companyUrl,
  isSubmitting,
  isLoadingMonitorResults,
  error,
  tenant,
  competitors,
  setCompetitors,
  changes,
  onMarkChangeRead,
  onBulkMarkChangesRead,
  resetToken,
  monitors,
  currentMonitorId,
  archives,
  archivesLoading,
  trackedCompetitorIds,
  isBulkMarkPending,
  onCreateArchive,
  onSwitchMonitor,
  onDeleteMonitor,
  onAddMonitor,
  onUpdateMonitorName,
  setError,
  setTrackedCompetitorIds,
}: ResultsViewProps) {
  const [isAddCompetitorOpen, setIsAddCompetitorOpen] = useState(false)
  const [competitorUrl, setCompetitorUrl] = useState("")
  const [isSavingCompetitor, setIsSavingCompetitor] = useState(false)

  const displayName = companyUrl ? toDisplayName(companyUrl) : "your company"
  const stageReady = {
    tenant: Boolean(tenant),
    competitors: competitors.length > 0,
    changes: changes.length > 0,
  }
  const unreadCount = changes.reduce((count, change) => (change.readAt ? count : count + 1), 0)

  /**
   * Handles adding a new competitor manually via the dialog form
   */
  const handleAddCompetitor = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedUrl = competitorUrl.trim()
    if (!trimmedUrl || !currentMonitorId) {
      setError('Select a monitor and provide a competitor URL before adding')
      return
    }

    const absoluteUrl = ensureAbsoluteUrl(trimmedUrl)
    const competitorId = extractCompetitorId(absoluteUrl)
    setIsSavingCompetitor(true)

    try {
      const response = await apiTrackCompetitor(competitorId, {
        monitorId: currentMonitorId,
        displayName: toDisplayName(absoluteUrl),
        url: absoluteUrl,
        source: 'manual',
        description: 'Added manually',
      })

      const insight = response.competitor
        ? insightFromTracked(response.competitor)
        : {
            id: competitorId,
            competitorId,
            displayName: toDisplayName(absoluteUrl),
            primaryUrl: absoluteUrl,
            briefDescription: 'Added manually',
            source: 'manual',
            confidence: 0.5,
            demographics: 'Undisclosed audience',
          }

      setCompetitors((previous) => {
        const filtered = previous.filter((item) => item.id !== insight.id)
        return [toCompetitorCard(insight), ...filtered]
      })

      setTrackedCompetitorIds((previous) =>
        response.trackedCompetitorIds.length
          ? response.trackedCompetitorIds
          : Array.from(new Set([...previous, insight.id]))
      )

      setCompetitorUrl('')
      setIsAddCompetitorOpen(false)
    } catch (err) {
      console.error('Failed to add competitor', err)
      setError(err instanceof Error ? err.message : 'Unable to add competitor')
    } finally {
      setIsSavingCompetitor(false)
    }
  }

  /**
   * Handles removing a competitor from the list
   */
  const handleRemoveCompetitor = async (competitorId: string) => {
    if (currentMonitorId) {
      try {
        const response = await apiUntrackCompetitor(competitorId, { monitorId: currentMonitorId })
        setTrackedCompetitorIds(response.trackedCompetitorIds)
      } catch (err) {
        console.error('Failed to untrack competitor', err)
        setError(err instanceof Error ? err.message : 'Unable to untrack competitor')
      }
    }

    setCompetitors((previous) => previous.filter(competitor => competitor.id !== competitorId))
  }

  useEffect(() => {
    // Ensure we start at the top of the page
    window.scrollTo({ top: 0, behavior: "auto" })
    
    // Set hash after a small delay to prevent automatic scrolling
    const timer = setTimeout(() => {
      window.history.replaceState({}, "", "#section-profile")
    }, 100)
    
    return () => clearTimeout(timer)
  }, [])


  const navItems = [
    { id: "section-profile", label: "Profile" },
    { id: "section-competitors", label: "Competitors" },
    { id: "section-radar", label: unreadCount ? `Radar (${unreadCount})` : "Radar" },
    { id: "section-archives", label: "Archives" },
    { id: "section-mcp", label: "MCP Integration" },
  ]

  return (
    <div className="flex w-full flex-col">
      {/* Top navigation bar - full width and sticky */}
      <div className="sticky top-0 z-50 flex items-center justify-between border-b border-border bg-background/90 px-6 py-4 text-foreground backdrop-blur dark:bg-background/70">
        <span className="-mt-1 text-3xl font-semibold tracking-[0.35em]">opps_</span>
        <div className="flex items-center gap-4 sm:gap-6">
          <MonitorDropdown
            monitors={monitors}
            currentMonitorId={currentMonitorId}
            onSwitchMonitor={onSwitchMonitor}
            onDeleteMonitor={onDeleteMonitor}
            onAddMonitor={onAddMonitor}
            onUpdateMonitorName={onUpdateMonitorName}
          />
          <ModeToggle />
          <button 
            type="button"
            className="text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground"
          >
            Account
          </button>
          <button 
            type="button"
            className="text-sm text-muted-foreground transition-colors duration-200 hover:text-foreground"
            onClick={() => {
              try {
                if (typeof window !== 'undefined') {
                  window.localStorage.removeItem('auth_token')
                  window.location.replace(window.location.pathname)
                }
              } catch {
                // noop
              }
            }}
          >
            Log out
          </button>
        </div>
      </div>

      {/* Main layout with sidebar and content */}
      <div className="flex w-full flex-col lg:flex-row">
        {/* Left sidebar */}
        <div className="lg:sticky lg:top-[73px] lg:h-[calc(100vh-73px)] lg:w-64 lg:border-r lg:border-border lg:bg-sidebar">
          <div className="px-6 py-4">
            <Scrollspy
              key={resetToken}
              offset={96}
              defaultActiveId="section-profile"
              className="flex flex-col gap-2 text-xs font-medium text-muted-foreground"
            >
              {navItems.map((item) => (
                <Button
                  key={item.id}
                  variant="ghost"
                  data-scrollspy-anchor={item.id}
                  className="w-full justify-start px-4 py-2 text-left text-muted-foreground transition data-[active=true]:bg-accent data-[active=true]:text-foreground"
                >
                  {item.label}
                </Button>
              ))}
            </Scrollspy>
          </div>
        </div>

        {/* Main content area */}
        <div className="flex-1 py-12 lg:py-16">
          <div className="mx-auto max-w-4xl px-6">
          <div className="space-y-6 pb-8">
            <section id="section-profile" className="scroll-mt-24">
              <TenantPanel
                tenant={tenant}
                displayName={displayName}
                isLoading={(isSubmitting || isLoadingMonitorResults) && !stageReady.tenant}
              />
            </section>

            <section id="section-competitors" className="scroll-mt-24">
              <CompetitorsPanel
                competitors={competitors}
                isLoading={(isSubmitting || isLoadingMonitorResults) && !stageReady.competitors}
                isAddCompetitorOpen={isAddCompetitorOpen}
                setIsAddCompetitorOpen={setIsAddCompetitorOpen}
                competitorUrl={competitorUrl}
                setCompetitorUrl={setCompetitorUrl}
                onAddCompetitor={handleAddCompetitor}
                onRemoveCompetitor={handleRemoveCompetitor}
                trackedCompetitorIds={trackedCompetitorIds}
                isSaving={isSavingCompetitor}
              />
            </section>

            <section id="section-radar" className="scroll-mt-24">
              <ChangesPanel
                changes={changes}
                isLoading={(isSubmitting || isLoadingMonitorResults) && !stageReady.changes}
                onMarkRead={onMarkChangeRead}
                onBulkMarkRead={onBulkMarkChangesRead}
                unreadCount={unreadCount}
                isBulkActionPending={isBulkMarkPending}
              />
            </section>

            <section id="section-archives" className="scroll-mt-24">
              <ArchivePanel
                archives={archives}
                isLoading={archivesLoading}
                onCreateArchive={onCreateArchive}
              />
            </section>

            <section id="section-mcp" className="scroll-mt-24">
              <McpPanel />
            </section>

            {isSubmitting && (
              <p className="text-sm text-muted-foreground">Processing analysis stream...</p>
            )}

            {error && (
              <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-xs text-destructive">
                {error}
              </p>
            )}
          </div>
          </div>
        </div>
      </div>
    </div>
  )
}

type MonitorDropdownProps = {
  monitors: Monitor[]
  currentMonitorId: string | null
  onSwitchMonitor: (monitorId: string) => void
  onDeleteMonitor: (monitorId: string) => void
  onAddMonitor: () => void
  onUpdateMonitorName: (monitorId: string, newName: string) => void
}

type DropdownSelectEvent = Event & {
  detail?: { originalEvent?: Event }
}

type MonitorDropdownRowProps = {
  monitor: Monitor
  isEditing: boolean
  onSelect: (event: Event, isEditing: boolean) => void
  onStartEdit: () => void
  onDelete: () => void
  onSave: (newName: string) => void
  onCancel: () => void
}

function MonitorDropdown({
  monitors,
  currentMonitorId,
  onSwitchMonitor,
  onDeleteMonitor,
  onAddMonitor,
  onUpdateMonitorName,
}: MonitorDropdownProps) {
  const [editingMonitorId, setEditingMonitorId] = useState<string | null>(null)
  const currentMonitor = monitors.find(monitor => monitor.id === currentMonitorId)
  const displayText = currentMonitor
    ? currentMonitor.displayName ?? currentMonitor.name
    : "Select Monitor"

  const resetEditing = () => setEditingMonitorId(null)

  const handleStartEdit = (monitorId: string) => {
    setEditingMonitorId(monitorId)
  }

  const handleSaveEdit = (monitorId: string, newName: string) => {
    onUpdateMonitorName(monitorId, newName)
    resetEditing()
  }

  const handleCancelEdit = () => {
    resetEditing()
  }

  const getOriginalTarget = (event: DropdownSelectEvent): HTMLElement | null => {
    const originalEventTarget = event.detail?.originalEvent?.target

    if (originalEventTarget instanceof HTMLElement) {
      return originalEventTarget
    }

    return event.target instanceof HTMLElement ? event.target : null
  }

  const handleMonitorSelect = (
    event: DropdownSelectEvent,
    monitorId: string,
    isEditing: boolean,
  ) => {
    const target = getOriginalTarget(event)
    const interactingWithInlineControls = Boolean(
      target?.closest("button, input, textarea"),
    )

    if (isEditing || interactingWithInlineControls) {
      event.preventDefault()
      return
    }

    resetEditing()
    onSwitchMonitor(monitorId)
  }

  return (
    <DropdownMenu onOpenChange={(isOpen) => !isOpen && resetEditing()}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground transition-colors duration-200 hover:bg-accent hover:text-foreground"
        >
          <span>{displayText}</span>
          <ChevronDown className="h-4 w-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64 rounded-xl border border-border bg-card text-foreground shadow-xl">
        {monitors.length > 0 && (
          <>
            {monitors.map((monitor) => (
              <MonitorDropdownRow
                key={monitor.id}
                monitor={monitor}
                isEditing={editingMonitorId === monitor.id}
                onSelect={(event, isEditing) =>
                  handleMonitorSelect(event as DropdownSelectEvent, monitor.id, isEditing)
                }
                onStartEdit={() => handleStartEdit(monitor.id)}
                onDelete={() => {
                  resetEditing()
                  onDeleteMonitor(monitor.id)
                }}
                onSave={(newName) => handleSaveEdit(monitor.id, newName)}
                onCancel={handleCancelEdit}
              />
            ))}
            <DropdownMenuSeparator className="bg-border" />
          </>
        )}
        <DropdownMenuItem
          className="flex items-center gap-2 px-3 py-2 text-emerald-600 hover:bg-emerald-500/10 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
          onSelect={(event) => {
            event.preventDefault()
            resetEditing()
            onAddMonitor()
          }}
        >
          <Plus className="h-4 w-4" />
          <span className="text-sm font-medium">Add Monitor</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function MonitorDropdownRow({
  monitor,
  isEditing,
  onSelect,
  onStartEdit,
  onDelete,
  onSave,
  onCancel,
}: MonitorDropdownRowProps) {
  const itemRef = useRef<HTMLDivElement | null>(null)
  const rawDomainSource = monitor.canonicalUrl ?? monitor.url ?? ''
  const derivedDomain = rawDomainSource ? formatDisplayUrl(rawDomainSource) : '—'
  const domainLabel = monitor.displayDomain ?? derivedDomain
  const competitorTotal = monitor.trackedCompetitorCount ?? monitor.trackedCompetitorIds.length
  const secondaryText = competitorTotal > 0 ? `${domainLabel} • ${competitorTotal} tracked` : domainLabel

  return (
    <DropdownMenuItem
      ref={itemRef}
      className="flex items-center px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
      onSelect={(event) => onSelect(event, isEditing)}
    >
      <div className="flex min-w-0 flex-1 flex-col">
        <InlineEdit
          value={monitor.name}
          onSave={onSave}
          onCancel={onCancel}
          className="text-sm"
          maxLength={22}
          isEditing={isEditing}
          getBoundaryElement={() => itemRef.current}
        />
        <span className="text-xs text-muted-foreground">{secondaryText}</span>
      </div>
      <div className="ml-2 flex items-center gap-1">
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            onStartEdit()
          }}
          className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title="Edit name"
        >
          <Edit3 className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            onDelete()
          }}
          className="rounded p-1 text-muted-foreground/70 transition-colors hover:bg-destructive/10 hover:text-destructive"
          title="Delete monitor"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </DropdownMenuItem>
  )
}

type TenantPanelProps = {
  tenant: TenantSnapshot | null
  displayName: string
  isLoading: boolean
}

function TenantPanel({ tenant, displayName, isLoading }: TenantPanelProps) {
  return (
    <StageCard title="Company overview">
      {tenant ? (
        <div className="space-y-4 text-left text-foreground">
          <div>
            <div className="text-xl font-semibold text-foreground">{tenant.name}</div>
            <a
              href={tenant.url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex items-center gap-2 text-sm text-emerald-600 transition-colors hover:text-emerald-500 dark:text-emerald-400 dark:hover:text-emerald-300"
            >
              {formatDisplayUrl(tenant.url)}
              <span aria-hidden>↗</span>
            </a>
            <p className="mt-2 text-sm text-muted-foreground">{tenant.description}</p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <InfoTile label="Target market" value={tenant.targetMarket} />
            <InfoTile
              label="Key features"
              value={tenant.keyFeatures.join(" · ") || "Awaiting feature set"}
            />
          </div>
        </div>
      ) : (
        <StagePlaceholder
          message={`Waiting on profile for ${displayName}.`}
          isLoading={isLoading}
          loadingLabel="Building company overview..."
        />
      )}
    </StageCard>
  )
}

type CompetitorsPanelProps = {
  competitors: CardItem[]
  isLoading: boolean
  isAddCompetitorOpen: boolean
  setIsAddCompetitorOpen: (open: boolean) => void
  competitorUrl: string
  setCompetitorUrl: (url: string) => void
  onAddCompetitor: (event: React.FormEvent<HTMLFormElement>) => void
  onRemoveCompetitor: (id: string) => void
  trackedCompetitorIds: string[]
  isSaving: boolean
}

function CompetitorsPanel({ 
  competitors, 
  isLoading, 
  isAddCompetitorOpen, 
  setIsAddCompetitorOpen, 
  competitorUrl, 
  setCompetitorUrl, 
  onAddCompetitor,
  onRemoveCompetitor,
  trackedCompetitorIds,
  isSaving,
}: CompetitorsPanelProps) {
  const trackedCount = trackedCompetitorIds.length
  const surfacedCount = competitors.length
  const description = surfacedCount
    ? `${surfacedCount} competitors surfaced · ${trackedCount} tracked`
    : 'No competitors found'

  return (
    <StageCard
      title="Competitors"
      cardClassName="relative"
      description={description}
    >
      <div className="space-y-4">
        {competitors.length ? (
          <ExpandableCard
            items={competitors.map(competitor => ({
              ...competitor,
              onRemove: () => onRemoveCompetitor(competitor.id)
            }))}
            className="bg-transparent text-left text-foreground"
          />
        ) : (
          <StagePlaceholder
            message="No competitor signals yet."
            isLoading={isLoading}
            loadingLabel="Finding competitors..."
          />
        )}
        
        <div className="flex justify-end border-t border-border pt-4">
          <Dialog open={isAddCompetitorOpen} onOpenChange={setIsAddCompetitorOpen}>
            <DialogTrigger asChild>
              <Button 
                variant="outline" 
                className="border-border text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isLoading || isSaving}
                isLoading={isSaving}
              >
                Add Competitor
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[425px] border border-border bg-popover text-popover-foreground">
              <form onSubmit={onAddCompetitor}>
                <DialogHeader>
                  <DialogTitle className="text-foreground">Add Competitor</DialogTitle>
                  <DialogDescription className="text-muted-foreground">
                    Add a competitor by entering their website URL.
                  </DialogDescription>
                </DialogHeader>
                <div className="grid gap-4 py-4">
                  <div className="grid gap-2">
                    <Label htmlFor="competitor-url" className="text-foreground">
                      Website URL
                    </Label>
                    <Input
                      id="competitor-url"
                      value={competitorUrl}
                      onChange={(e) => setCompetitorUrl(e.target.value)}
                      placeholder="https://example.com"
                      className="border border-input bg-background text-foreground placeholder:text-muted-foreground"
                    />
                  </div>
                </div>
                <DialogFooter>
                  <DialogClose asChild>
                    <Button type="button" variant="outline" className="border-border text-foreground hover:bg-accent">
                      Cancel
                    </Button>
                  </DialogClose>
                  <Button type="submit" className="bg-primary text-primary-foreground hover:bg-primary/90">
                    Add Competitor
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </StageCard>
  )
}

type MonitorCreateDialogProps = {
  open: boolean
  isSubmitting: boolean
  form: { url: string; name: string }
  onOpenChange: (open: boolean) => void
  onChange: (form: { url: string; name: string }) => void
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
}

function MonitorCreateDialog({
  open,
  isSubmitting,
  form,
  onOpenChange,
  onChange,
  onSubmit,
}: MonitorCreateDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px] border border-border bg-popover text-popover-foreground">
        <form onSubmit={onSubmit}>
          <DialogHeader>
            <DialogTitle className="text-foreground">Add Monitor</DialogTitle>
            <DialogDescription className="text-muted-foreground">
              Create a monitor to track future analyses for this domain.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="monitor-url" className="text-foreground">
                Website URL
              </Label>
              <Input
                id="monitor-url"
                value={form.url}
                onChange={(event) => onChange({ ...form, url: event.target.value })}
                placeholder="https://example.com"
                className="border border-input bg-background text-foreground placeholder:text-muted-foreground"
                autoFocus
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="monitor-name" className="text-foreground">
                Monitor name (optional)
              </Label>
              <Input
                id="monitor-name"
                value={form.name}
                onChange={(event) => onChange({ ...form, name: event.target.value })}
                placeholder="Acme homepage"
                className="border border-input bg-background text-foreground placeholder:text-muted-foreground"
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline" className="border-border text-foreground hover:bg-accent">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" className="bg-primary text-primary-foreground hover:bg-primary/90" isLoading={isSubmitting}>
              Create monitor
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

type ChangesPanelProps = {
  changes: ChangeRadarEntry[]
  isLoading: boolean
  onMarkRead: (id: string) => Promise<void> | void
  onBulkMarkRead?: (ids: string[]) => Promise<void> | void
  unreadCount: number
  isBulkActionPending: boolean
}

function ChangesPanel({
  changes,
  isLoading,
  onMarkRead,
  onBulkMarkRead,
  unreadCount,
  isBulkActionPending,
}: ChangesPanelProps) {
  const [searchQuery, setSearchQuery] = useState("")
  const [searchPage, setSearchPage] = useState(0)
  const [selectedChanges, setSelectedChanges] = useState<Set<string>>(new Set())
  const [isSelectionMode, setIsSelectionMode] = useState(false)
  const [pageSize, setPageSize] = useState(8)
  const [threatThreshold, setThreatThreshold] = useState(0)
  const [emailAlerts, setEmailAlerts] = useState(false)
  const [isAlertDrawerOpen, setIsAlertDrawerOpen] = useState(false)
  const [alertThreatThreshold, setAlertThreatThreshold] = useState(5)
  
  // Filter changes based on search query and threat level
  const filteredChanges = changes.filter(change => {
    // Search query filter
    const matchesSearch = !searchQuery.trim() || (() => {
      const domain = formatDisplayUrl(change.url).toLowerCase()
      const content = change.content.toLowerCase()
      const query = searchQuery.toLowerCase()
      return domain.includes(query) || content.includes(query)
    })()
    
    // Threat threshold filter
    const matchesThreatThreshold = change.threatLevel >= threatThreshold
    
    return matchesSearch && matchesThreatThreshold
  })
  
  // Calculate pagination for filtered results
  const filteredTotalPages = Math.max(1, Math.ceil(filteredChanges.length / pageSize))
  const filteredCurrentPage = Math.min(searchPage, filteredTotalPages - 1)
  const filteredStartIndex = filteredCurrentPage * pageSize
  const visibleFilteredChanges = filteredChanges.slice(filteredStartIndex, filteredStartIndex + pageSize)
  const filteredCanPrevious = filteredCurrentPage > 0
  const filteredCanNext = filteredCurrentPage < filteredTotalPages - 1
  
  // Reset search page when search query or threat threshold changes
  useEffect(() => {
    setSearchPage(0)
  }, [searchQuery, threatThreshold])
  
  // Reset page when page size changes
  useEffect(() => {
    setSearchPage(0)
  }, [pageSize])
  
  // Clear selections and exit selection mode when search or threat threshold changes
  useEffect(() => {
    setSelectedChanges(new Set())
    setIsSelectionMode(false)
  }, [searchQuery, threatThreshold])
  
  // Select handlers
  const handleSelectChange = (changeId: string, isSelected: boolean) => {
    setIsSelectionMode(true) // Enable selection mode when user starts selecting
    setSelectedChanges(prev => {
      const newSet = new Set(prev)
      if (isSelected) {
        newSet.add(changeId)
      } else {
        newSet.delete(changeId)
      }
      return newSet
    })
  }
  
  const handleSelectAll = (isSelected: boolean) => {
    setIsSelectionMode(true) // Enable selection mode when user clicks select all
    if (isSelected) {
      setSelectedChanges(new Set(visibleFilteredChanges.map(change => change.id)))
    } else {
      setSelectedChanges(new Set())
    }
  }
  
  const handleExitSelectionMode = () => {
    setSelectedChanges(new Set())
    setIsSelectionMode(false)
  }
  
  const handleBulkMarkRead = async () => {
    if (!selectedChanges.size || isBulkActionPending) return
    const ids = Array.from(selectedChanges)
    if (onBulkMarkRead) {
      await onBulkMarkRead(ids)
    } else {
      await Promise.all(ids.map((changeId) => Promise.resolve(onMarkRead(changeId))))
    }
    setSelectedChanges(new Set())
    setIsSelectionMode(false)
  }
  
  const isAllSelected = visibleFilteredChanges.length > 0 && 
    visibleFilteredChanges.every(change => selectedChanges.has(change.id))
  const isIndeterminate = selectedChanges.size > 0 && !isAllSelected
  
  const changeCards = adaptChangesToCards(visibleFilteredChanges, onMarkRead, selectedChanges, handleSelectChange, isSelectionMode)
  
  return (
    <Drawer open={isAlertDrawerOpen} onOpenChange={setIsAlertDrawerOpen}>
      <StageCard
        title="Change radar"
        description={unreadCount ? `${unreadCount} unread` : "All caught up"}
        headerActions={
          <DrawerTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-3 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              Alert Settings {emailAlerts ? `≥${alertThreatThreshold}` : ''}
            </Button>
          </DrawerTrigger>
        }
      >
        {changes.length ? (
          <div className="space-y-4">
            {/* Search bar */}
            <div className="flex items-center gap-3">
              <Input
                placeholder="Search changes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="border-input bg-background text-foreground placeholder:text-muted-foreground"
              />
              
              {/* Page size selector */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Show:</span>
                <select
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                  className="h-8 rounded border border-input bg-background px-2 text-xs text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/40"
                >
                  <option value={8}>8</option>
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                  <option value={40}>40</option>
                </select>
              </div>
            </div>
            
            {/* Threat Level Filter */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-foreground">Threat Threshold</span>
                <span className="text-xs text-muted-foreground">
                  {threatThreshold}
                </span>
              </div>
              <Slider
                value={[threatThreshold]}
                onValueChange={(value) => setThreatThreshold(value[0])}
                max={10}
                min={0}
                step={0.5}
                className="w-full"
              />
            </div>

            <DrawerContent className="border border-border bg-card text-foreground">
              <div className="mx-auto w-full max-w-sm">
                <DrawerHeader className="text-center">
                  <DrawerTitle className="font-roboto text-xl font-semibold text-foreground">Alert Settings</DrawerTitle>
                  <DrawerDescription className="font-roboto text-muted-foreground">
                    Configure your notification preferences
                  </DrawerDescription>
                </DrawerHeader>

                <div className="p-4 pb-0">
                  <div className="mb-6 flex items-center justify-center space-x-2">
                    <button
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                      onClick={() => setAlertThreatThreshold(Math.max(0, alertThreatThreshold - 0.5))}
                      disabled={alertThreatThreshold <= 0}
                    >
                      <span className="font-medium">−</span>
                    </button>
                    <div className="flex-1 text-center">
                      <div className="font-roboto text-4xl font-bold tracking-tighter text-foreground">
                        {alertThreatThreshold}
                      </div>
                      <div className="font-roboto text-xs uppercase text-muted-foreground">
                        Threat Level
                      </div>
                    </div>
                    <button
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                      onClick={() => setAlertThreatThreshold(Math.min(10, alertThreatThreshold + 0.5))}
                      disabled={alertThreatThreshold >= 10}
                    >
                      <span className="font-medium">+</span>
                    </button>
                  </div>

                  {/* Email Alerts Toggle */}
                  <div className="mb-4 flex items-center justify-between">
                    <div>
                      <Label htmlFor="email-alerts" className="font-roboto font-medium text-foreground">
                        Email Notifications
                      </Label>
                      <p className="mt-1 text-sm font-roboto text-muted-foreground">
                        Get notified when changes occur
                      </p>
                    </div>
                    <Checkbox
                      id="email-alerts"
                      checked={emailAlerts}
                      onCheckedChange={(checked: boolean) => setEmailAlerts(checked)}
                      className="border-input data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground"
                    />
                  </div>
                </div>

                <DrawerFooter>
                  <Button 
                    onClick={() => setIsAlertDrawerOpen(false)}
                    className="font-roboto bg-primary text-primary-foreground hover:bg-primary/90"
                  >
                    Submit
                  </Button>
                  <Button 
                    onClick={() => setIsAlertDrawerOpen(false)}
                    className="font-roboto" variant="outline"
                  >
                    Cancel
                  </Button>
                </DrawerFooter>
              </div>
            </DrawerContent>

            {filteredChanges.length > 0 ? (
              <>
                {/* Select controls - only show when in selection mode */}
                {isSelectionMode && (
                  <div className="flex items-center justify-between border-b border-border pb-3">
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={isAllSelected}
                          ref={(input) => {
                            if (input) input.indeterminate = isIndeterminate
                          }}
                          onChange={(e) => handleSelectAll(e.target.checked)}
                          className="h-4 w-4 rounded border-input bg-background text-primary focus:ring-primary focus:ring-2"
                        />
                        <span className="text-sm text-muted-foreground">
                          {selectedChanges.size > 0 ? `${selectedChanges.size} selected` : 'Select all'}
                        </span>
                      </label>
                    </div>
                    
                    <div className="flex items-center gap-2">
                      {selectedChanges.size > 0 && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleBulkMarkRead}
                          className="h-8 px-3 text-xs border-border text-foreground hover:bg-accent"
                          disabled={isBulkActionPending}
                          isLoading={isBulkActionPending}
                        >
                          Mark as read ({selectedChanges.size})
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={handleExitSelectionMode}
                        className="h-8 px-3 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                      >
                        {selectedChanges.size > 0 ? 'Clear' : 'Cancel'}
                      </Button>
                    </div>
                  </div>
                )}

                {/* Selection mode trigger - show when not in selection mode */}
                {!isSelectionMode && (
                  <div className="flex items-center justify-end border-b border-border pb-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setIsSelectionMode(true)}
                      disabled={isBulkActionPending}
                      className="h-8 px-3 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                    >
                      Select items
                    </Button>
                  </div>
                )}

                <div className="flex flex-col">
                  {changeCards.length > 0 ? (
                    <>
                      <ExpandableCard
                        items={changeCards}
                        className="bg-transparent p-0 text-left text-foreground"
                      />
                      {filteredTotalPages > 1 && (
                        <ChangePagination
                          page={filteredCurrentPage}
                          totalPages={filteredTotalPages}
                          canPrevious={filteredCanPrevious}
                          canNext={filteredCanNext}
                          onPrevious={() => setSearchPage(prev => Math.max(0, prev - 1))}
                          onNext={() => setSearchPage(prev => Math.min(filteredTotalPages - 1, prev + 1))}
                        />
                      )}
                    </>
                  ) : (
                    <div className="flex min-h-[200px] items-center justify-center">
                      <p className="text-sm text-muted-foreground">No changes found matching "{searchQuery}"</p>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex min-h-[200px] items-center justify-center">
                <p className="text-sm text-muted-foreground">No changes found matching "{searchQuery}"</p>
              </div>
            )}
          </div>
        ) : (
          <StagePlaceholder
            message="Monitoring competitor feeds."
            isLoading={isLoading}
            loadingLabel="Tracking live moves..."
          />
        )}
      </StageCard>
    </Drawer>
  )
}

function toCompetitorCard(insight: CompetitorInsight, isTracked = true): CardItem {
  const displayUrl = formatDisplayUrl(insight.primaryUrl)
  const confidencePercent = Math.round((insight.confidence ?? 0.5) * 100)
  const domain = domainForFavicon(insight.primaryUrl)
  const metadata = isTracked
    ? insight.demographics
    : `${insight.demographics || 'Undisclosed audience'} · untracked`

  return {
    id: insight.id,
    title: insight.displayName,
    subtitle: displayUrl,
    icon: <CompetitorIcon domain={domain} name={insight.displayName} />,
    description: `Confidence: ${confidencePercent}% · Source: ${insight.source}`,
    details: insight.briefDescription,
    metadata,
    extended: [
      { label: 'Primary URL', value: displayUrl || 'Not published' },
      { label: 'Audience', value: insight.demographics || 'Undisclosed audience' },
      { label: 'Signal source', value: insight.source || 'analysis' },
      { label: 'Confidence score', value: `${confidencePercent}%` },
    ],
    link: insight.primaryUrl || undefined,
  }
}

function mergeChangeReadState(
  previous: ChangeRadarEntry[],
  next: ChangeInsight[],
): ChangeRadarEntry[] {
  const previousById = new Map(previous.map((entry) => [entry.id, entry]))
  return next.map((entry) => {
    const existing = previousById.get(entry.id)
    return existing ? { ...entry, readAt: existing.readAt ?? entry.readAt } : entry
  })
}

function insightFromTracked(record: TrackedCompetitor): CompetitorInsight {
  return {
    id: record.id,
    competitorId: record.competitorId,
    displayName: record.displayName,
    primaryUrl: record.primaryUrl,
    briefDescription: record.briefDescription || 'Added manually',
    source: record.source || 'analysis',
    confidence: record.confidence ?? 0.5,
    demographics: record.demographics || 'Undisclosed audience',
  }
}

function arraysEqual<T>(left: T[], right: T[]): boolean {
  if (left.length !== right.length) {
    return false
  }
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return false
    }
  }
  return true
}

function ensureAbsoluteUrl(raw: string): string {
  if (!raw) return ''
  if (raw.startsWith('http://') || raw.startsWith('https://')) {
    return raw
  }
  return `https://${raw}`
}

// Mirrors backend normalization so we can safely compare monitor URLs client-side.
function normalizeMonitorUrl(raw: string): string {
  const candidate = raw.trim()
  if (!candidate) {
    return ''
  }

  try {
    const url = new URL(ensureAbsoluteUrl(candidate))
    const host = (url.hostname || '').toLowerCase()

    if (!host) {
      return candidate.toLowerCase()
    }

    let normalized = host
    const path = url.pathname.replace(/\/+$/, '')
    if (path && path !== '/') {
      normalized += path
    }

    if (url.search) {
      normalized += url.search
    }

    if (url.hash) {
      normalized += url.hash
    }

    return normalized
  } catch {
    return candidate.toLowerCase()
  }
}

function extractCompetitorId(rawUrl: string): string {
  try {
    const url = new URL(ensureAbsoluteUrl(rawUrl))
    return url.hostname.replace(/^www\./, '') || rawUrl
  } catch {
    return rawUrl.replace(/^https?:\/\//, '').split('/')[0] || rawUrl
  }
}

type StageCardProps = {
  title: string
  description?: string
  children: ReactNode
  cardClassName?: string
  headerActions?: ReactNode
}

function StageCard({ title, description, children, cardClassName, headerActions }: StageCardProps) {
  return (
    <div
      className={`rounded-2xl border border-border bg-card p-6 shadow-sm backdrop-blur-sm transition-colors dark:border-white/12 dark:bg-[hsl(240,10%,14%)] sm:p-7 ${cardClassName ?? ""}`}
    >
      <div className="flex flex-col gap-3 text-left sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-1">
          <h3 className="text-2xl font-semibold text-foreground">{title}</h3>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        {headerActions ? (
          <div className="flex items-center gap-2 sm:justify-end">
            {headerActions}
          </div>
        ) : null}
      </div>
      <div className="mt-5 space-y-4">{children}</div>
    </div>
  )
}

type ChangePaginationProps = {
  page: number
  totalPages: number
  canPrevious: boolean
  canNext: boolean
  onPrevious: () => void
  onNext: () => void
}

function ChangePagination({ page, totalPages, canPrevious, canNext, onPrevious, onNext }: ChangePaginationProps) {
  return (
    <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
      <span className="font-mono tracking-[0.25em]">
        Page {page + 1} / {totalPages}
      </span>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onPrevious}
          disabled={!canPrevious}
          className="rounded-full border border-border px-3 py-1 tracking-[0.25em] text-muted-foreground transition enabled:hover:bg-accent enabled:hover:text-foreground disabled:opacity-40"
        >
          Prev
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!canNext}
          className="rounded-full border border-border px-3 py-1 tracking-[0.25em] text-muted-foreground transition enabled:hover:bg-accent enabled:hover:text-foreground disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  )
}

function McpPanel() {
  return (
    <StageCard title="MCP integration" description="Connect opp with AI tooling">
      <div className="py-4 text-center">
        <TextShimmer className="font-roboto text-lg text-muted-foreground" duration={2}>
          Coming soon
        </TextShimmer>
      </div>
    </StageCard>
  )
}

type ArchivePanelProps = {
  archives: ArchiveItem[]
  isLoading: boolean
  onCreateArchive: () => void
}

function ArchivePanel({ archives, isLoading, onCreateArchive }: ArchivePanelProps) {
  return (
    <StageCard
      title="Archive"
      description={archives.length ? `${archives.length} saved snapshots` : 'Capture completed analyses'}
      headerActions={
        <Button
          variant="ghost"
          size="sm"
          className="h-8 px-3 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          onClick={onCreateArchive}
        >
          Save snapshot
        </Button>
      }
    >
      {isLoading ? (
        <StagePlaceholder message="Fetching archives..." isLoading={true} />
      ) : archives.length ? (
        <div className="space-y-3">
          {archives.map((archive) => (
            <div
              key={archive.id}
              className="rounded-lg border border-border bg-card/70 px-4 py-3 text-left text-sm text-foreground"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">{archive.title}</span>
                <span className="text-xs text-muted-foreground">{formatTimestamp(archive.createdAt)}</span>
              </div>
              {archive.metadata && archive.metadata.summary ? (
                <p className="mt-2 text-xs text-muted-foreground">{String(archive.metadata.summary)}</p>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <StagePlaceholder message="No archives yet. Save the current run to build your history." isLoading={false} />
      )}
    </StageCard>
  )
}

type StagePlaceholderProps = {
  message: string
  isLoading: boolean
  loadingLabel?: string
}

function StagePlaceholder({ message, isLoading, loadingLabel }: StagePlaceholderProps) {
  if (isLoading) {
    return (
      <div className="py-2 text-left">
        <TextShimmer 
          className="font-roboto text-base text-muted-foreground" 
          duration={2}
          spread={0.8}
        >
          {loadingLabel ?? "Working"}
        </TextShimmer>
      </div>
    )
  }

  return <p className="text-sm text-muted-foreground">{message}</p>
}


type InfoTileProps = {
  label: string
  value: string
}

function InfoTile({ label, value }: InfoTileProps) {
  return (
    <div className="rounded-xl border border-border bg-muted/40 px-4 py-3 backdrop-blur-sm dark:bg-muted/20">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="mt-1 text-sm text-foreground">{value}</div>
    </div>
  )
}



function adaptChangesToCards(
  changes: ChangeRadarEntry[], 
  onMarkRead: (id: string) => Promise<void> | void,
  selectedChanges: Set<string>,
  onSelectChange: (changeId: string, isSelected: boolean) => void,
  isSelectionMode: boolean
): CardItem[] {
  return changes.map((change) => {
    const domain = formatDisplayUrl(change.url)
    const threatLevel = change.threatLevel.toFixed(1)
    const isRead = Boolean(change.readAt)
    const isSelected = selectedChanges.has(change.id)
    
    return {
      id: change.id,
      title: domain,
      subtitle: formatTimestamp(change.timestamp),
      icon: null,
      description: `Threat: ${threatLevel}`,
      details: change.content,
      metadata: change.whyMatter,
      extended: [
        { label: "Threat Level", value: `${threatLevel}` },
        { label: "Source", value: domain },
        { label: "Suggested Response", value: change.suggestions },
      ],
      link: change.url,
      onExpand: () => {
        if (!isRead) {
          onMarkRead(change.id)
        }
      },
      isUnread: !isRead,
      isSelected: isSelectionMode ? isSelected : false,
      onSelect: isSelectionMode ? (isSelected: boolean) => onSelectChange(change.id, isSelected) : undefined,
    }
  })
}


function toDisplayName(companyUrl: string): string {
  try {
    // Handle URLs that already have protocol
    const urlString = companyUrl.startsWith('http') ? companyUrl : `https://${companyUrl}`
    const url = new URL(urlString)
    const hostname = url.hostname.replace(/^www\./, "")
    const segments = hostname.split(".")
    const primary = segments[0] ?? companyUrl
    return primary.charAt(0).toUpperCase() + primary.slice(1)
  } catch {
    const sanitized = companyUrl.replace(/^www\./i, "").split(/[/.]/)[0]
    if (!sanitized) return "your company"
    return sanitized.charAt(0).toUpperCase() + sanitized.slice(1)
  }
}

function formatDisplayUrl(url: string): string {
  try {
    const target = url.startsWith("http") ? url : `https://${url}`
    const { hostname } = new URL(target)
    return hostname.replace(/^www\./, "")
  } catch {
    return url.replace(/^https?:\/\//, "")
  }
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) {
    return timestamp
  }

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

type CompetitorBadgeProps = {
  label: string
  seed: string
}

function CompetitorBadge({ label, seed }: CompetitorBadgeProps) {
  const palette = [
    "from-cyan-500/40 via-sky-400/30 to-indigo-500/40 text-sky-100",
    "from-emerald-500/40 via-lime-400/25 to-teal-500/40 text-emerald-100",
    "from-fuchsia-500/35 via-violet-400/25 to-purple-500/40 text-fuchsia-100",
    "from-amber-500/35 via-orange-400/25 to-rose-500/35 text-amber-100",
  ]
  const index = Math.abs(hashString(seed)) % palette.length
  const tone = palette[index]

  return (
    <div className={`flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br font-semibold uppercase tracking-wide ${tone}`}>
      <span className="text-xs">{label}</span>
    </div>
  )
}

function initialsFrom(value: string): string {
  const words = value.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return "--"
  if (words.length === 1) {
    return words[0].slice(0, 2).toUpperCase()
  }
  return (words[0][0] + words[1][0]).toUpperCase()
}

function hashString(value: string): number {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(index)
    hash |= 0
  }
  return hash
}

type CompetitorIconProps = {
  domain: string | null
  name: string
}

function CompetitorIcon({ domain, name }: CompetitorIconProps) {
  const [errored, setErrored] = useState(false)

  if (!domain || errored) {
    return <CompetitorBadge label={initialsFrom(name)} seed={name} />
  }

  const faviconUrl = buildFaviconUrl(domain, 64)

  return (
    <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-card/70">
      <img
        src={faviconUrl}
        alt={`${name} favicon`}
        className="h-8 w-8 rounded-full"
        onError={() => setErrored(true)}
        loading="lazy"
        decoding="async"
      />
    </div>
  )
}



function domainForFavicon(rawUrl: string): string | null {
  if (!rawUrl) return null
  try {
    const target = rawUrl.startsWith("http") ? rawUrl : `https://${rawUrl}`
    const { hostname } = new URL(target)
    return hostname.replace(/^www\./, "")
  } catch {
    return null
  }
}

function buildFaviconUrl(domain: string, size: number): string {
  const encodedDomain = encodeURIComponent(domain)
  const boundedSize = Math.max(16, Math.min(size, 128))
  return `https://www.google.com/s2/favicons?domain=${encodedDomain}&sz=${boundedSize}`
}
