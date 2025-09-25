"use client"

import { useCallback, useEffect, useRef } from "react"
import type { ReactNode, RefObject } from "react"

type ScrollspyProps = {
  children: ReactNode
  targetRef?: RefObject<HTMLElement | HTMLDivElement | Document | null | undefined>
  onUpdate?: (id: string) => void
  offset?: number
  smooth?: boolean
  className?: string
  dataAttribute?: string
  history?: boolean
  defaultActiveId?: string
}

export function Scrollspy({
  children,
  targetRef,
  onUpdate,
  className,
  offset = 0,
  smooth = true,
  dataAttribute = "scrollspy",
  history = true,
  defaultActiveId,
}: ScrollspyProps) {
  const selfRef = useRef<HTMLDivElement | null>(null)
  const anchorElementsRef = useRef<Element[] | null>(null)
  const prevIdTracker = useRef<string | null>(null)

  const setActiveSection = useCallback(
    (sectionId: string | null, force = false) => {
      if (!sectionId) return
      anchorElementsRef.current?.forEach((item) => {
        const id = item.getAttribute(`data-${dataAttribute}-anchor`)
        if (id === sectionId) {
          item.setAttribute("data-active", "true")
        } else {
          item.removeAttribute("data-active")
        }
      })
      if (onUpdate) onUpdate(sectionId)
      if (history && (force || prevIdTracker.current !== sectionId)) {
        window.history.replaceState({}, "", `#${sectionId}`)
      }
      prevIdTracker.current = sectionId
    },
    [dataAttribute, history, onUpdate]
  )

  const getScrollElement = useCallback((): Window | HTMLElement => {
    const current = targetRef?.current
    if (!current || (typeof Document !== "undefined" && current instanceof Document)) {
      return window
    }
    return current as HTMLElement
  }, [targetRef])

  const handleScroll = useCallback(() => {
    if (!anchorElementsRef.current || anchorElementsRef.current.length === 0) return
    const scrollElement = getScrollElement()
    const scrollTop =
      scrollElement === window
        ? window.scrollY || document.documentElement.scrollTop
        : (scrollElement as HTMLElement).scrollTop

    let activeIdx = 0
    let minDelta = Infinity
    anchorElementsRef.current.forEach((anchor, idx) => {
      const sectionId = anchor.getAttribute(`data-${dataAttribute}-anchor`)
      const sectionElement = sectionId ? document.getElementById(sectionId) : null
      if (!sectionElement) return

      let customOffset = offset
      const dataOffset = anchor.getAttribute(`data-${dataAttribute}-offset`)
      if (dataOffset) customOffset = parseInt(dataOffset, 10)

      const sectionTop = sectionElement.offsetTop - customOffset
      const delta = Math.abs(sectionTop - scrollTop)
      if (sectionTop <= scrollTop && delta < minDelta) {
        minDelta = delta
        activeIdx = idx
      }
    })

    if (scrollElement) {
      const scrollHeight =
        scrollElement === window
          ? document.documentElement.scrollHeight
          : (scrollElement as HTMLElement).scrollHeight
      const clientHeight =
        scrollElement === window
          ? window.innerHeight
          : (scrollElement as HTMLElement).clientHeight
      const isScrollable = scrollHeight - clientHeight > 2
      if (isScrollable && scrollTop + clientHeight >= scrollHeight - 2) {
        activeIdx = anchorElementsRef.current.length - 1
      }
    }

    const activeAnchor = anchorElementsRef.current[activeIdx]
    const sectionId = activeAnchor?.getAttribute(`data-${dataAttribute}-anchor`) || null
    setActiveSection(sectionId)
    anchorElementsRef.current.forEach((item, idx) => {
      if (idx !== activeIdx) {
        item.removeAttribute("data-active")
      }
    })
  }, [anchorElementsRef, dataAttribute, offset, setActiveSection, getScrollElement])

  const scrollTo = useCallback(
    (anchorElement: HTMLElement) => (event?: Event) => {
      if (event) event.preventDefault()
      const sectionId = anchorElement.getAttribute(`data-${dataAttribute}-anchor`)?.replace("#", "") || null
      if (!sectionId) return
      const sectionElement = document.getElementById(sectionId)
      if (!sectionElement) return

      const scrollToElement = getScrollElement()

      let customOffset = offset
      const dataOffset = anchorElement.getAttribute(`data-${dataAttribute}-offset`)
      if (dataOffset) {
        customOffset = parseInt(dataOffset, 10)
      }

      const scrollTop = sectionElement.offsetTop - customOffset

      scrollToElement.scrollTo({
        top: scrollTop,
        left: 0,
        behavior: smooth ? "smooth" : "auto",
      })
      setActiveSection(sectionId, true)
    },
    [dataAttribute, offset, smooth, setActiveSection, getScrollElement]
  )

  const scrollToHashSection = useCallback(() => {
    const hash = CSS.escape(window.location.hash.replace("#", ""))

    if (hash) {
      const targetElement = document.querySelector(`[data-${dataAttribute}-anchor="${hash}"]`) as HTMLElement | null
      if (targetElement) {
        scrollTo(targetElement)()
      }
    }
  }, [dataAttribute, scrollTo])

  useEffect(() => {
    if (selfRef.current) {
      anchorElementsRef.current = Array.from(selfRef.current.querySelectorAll(`[data-${dataAttribute}-anchor]`))
    }

    anchorElementsRef.current?.forEach((item) => {
      item.addEventListener("click", scrollTo(item as HTMLElement))
    })

    const scrollElement = getScrollElement()

    scrollElement.addEventListener("scroll", handleScroll)

    setTimeout(() => {
      if (defaultActiveId) {
        setActiveSection(defaultActiveId, true)
      }
      scrollToHashSection()
      setTimeout(() => {
        handleScroll()
      }, 100)
    }, 100)

    return () => {
      scrollElement.removeEventListener("scroll", handleScroll)
      anchorElementsRef.current?.forEach((item) => {
        item.removeEventListener("click", scrollTo(item as HTMLElement))
      })
    }
  }, [handleScroll, dataAttribute, scrollTo, scrollToHashSection, getScrollElement, defaultActiveId, setActiveSection])

  return (
    <div data-slot="scrollspy" className={className} ref={selfRef}>
      {children}
    </div>
  )
}
