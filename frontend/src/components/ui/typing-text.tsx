import { useEffect, useMemo, useState } from 'react'

import { cn } from '@/lib/utils'

interface TypingTextProps {
  texts: string[]
  className?: string
  speed?: number
  pauseDuration?: number
  loop?: boolean
  showCursor?: boolean
  cursor?: string
  cursorClassName?: string
}

export function TypingText({
  texts,
  className,
  speed = 100,
  pauseDuration = 1500,
  loop = true,
  showCursor = true,
  cursor = '|',
  cursorClassName,
}: TypingTextProps) {
  const sanitizedTexts = useMemo(() => texts.filter(Boolean), [texts])
  const [textIndex, setTextIndex] = useState(0)
  const [displayedText, setDisplayedText] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)
  const [isFinished, setIsFinished] = useState(false)

  useEffect(() => {
    if (sanitizedTexts.length === 0) return
    if (!loop && isFinished) return

    const currentText = sanitizedTexts[textIndex] ?? ''
    const isAtFullText = displayedText === currentText
    const isAtStart = displayedText.length === 0

    let timeout: ReturnType<typeof setTimeout>

    if (!isDeleting && !isAtFullText) {
      timeout = setTimeout(() => {
        setDisplayedText(currentText.slice(0, displayedText.length + 1))
      }, Math.max(speed, 20))
    } else if (!isDeleting && isAtFullText) {
      timeout = setTimeout(() => setIsDeleting(true), pauseDuration)
    } else if (isDeleting && !isAtStart) {
      timeout = setTimeout(() => {
        setDisplayedText(currentText.slice(0, displayedText.length - 1))
      }, Math.max(speed / 2, 20))
    } else if (isDeleting && isAtStart) {
      timeout = setTimeout(() => {
        const nextIndex = textIndex + 1
        if (nextIndex >= sanitizedTexts.length) {
          if (loop) {
            setTextIndex(0)
          } else {
            setIsFinished(true)
          }
        } else {
          setTextIndex(nextIndex)
        }
        setIsDeleting(false)
      }, 200)
    }

    return () => clearTimeout(timeout)
  }, [displayedText, isDeleting, sanitizedTexts, textIndex, loop, speed, pauseDuration, isFinished])

  useEffect(() => {
    if (sanitizedTexts.length === 0) {
      setDisplayedText('')
      setIsDeleting(false)
      setIsFinished(false)
      setTextIndex(0)
    }
  }, [sanitizedTexts])

  const currentRenderedText = sanitizedTexts.length ? displayedText : ''

  return (
    <span className={cn('inline-flex items-baseline gap-1', className)}>
      <span>{currentRenderedText}</span>
      {showCursor && !isFinished && (
        <span className={cn('inline-block animate-pulse', cursorClassName)}>{cursor}</span>
      )}
    </span>
  )
}
