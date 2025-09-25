"use client";

import type React from "react";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";
import { TextScramble } from "@/components/motion-primitives/text-scramble";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export interface CardItem {
  id: string;
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  description: string;
  details: string;
  metadata: string;
  extended?: Array<{
    label: string;
    value: string;
  }>;
  link?: string;
  onExpand?: () => void;
  onRemove?: () => void;
  confidence?: number;
  isUnread?: boolean;
  isSelected?: boolean;
  onSelect?: (isSelected: boolean) => void;
}

export interface ExpandableCardProps {
  items: CardItem[];
  className?: string;
}

export default function ExpandableCard({
  items,
  className,
}: ExpandableCardProps) {
  const [current, setCurrent] = useState<CardItem | null>(null);
  const [showScramble, setShowScramble] = useState(false);
  const [isRemoveDialogOpen, setIsRemoveDialogOpen] = useState(false);
  const ref = useOutsideClick(() => {
    setCurrent(null);
    setShowScramble(false);
  });

  return (
    <div className="">
      <AnimatePresence>
        {current ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none absolute inset-0 z-10 bg-background/50 bg-opacity-10 backdrop-blur-xl"
          />
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {current ? (
          <>
            <div className="absolute inset-0 z-10 grid place-items-center">
              <motion.div
                className="flex h-fit w-full max-w-xl cursor-pointer flex-col items-start gap-4 overflow-hidden rounded-2xl border border-border bg-card p-4 shadow-xl dark:bg-card/80"
                ref={ref}
                layoutId={`cardItem-${current.id}`}
                style={{ willChange: 'transform' }}
              >
                <div className="flex w-full items-center gap-4">
                  {current.icon && (
                    <motion.div layoutId={`cardItemIcon-${current.id}`}>
                      {current.icon}
                    </motion.div>
                  )}
                  <div className="flex grow items-center justify-between">
                    <div className="flex w-full flex-col gap-0.5">
                      <div className="flex w-full flex-row justify-between gap-0.5">
                        <motion.div
                          className="text-sm font-medium font-roboto text-primary"
                          layoutId={`cardItemTitle-${current.id}`}
                        >
                          {current.title}
                        </motion.div>
                        {current.onRemove && (
                          <Dialog open={isRemoveDialogOpen} onOpenChange={setIsRemoveDialogOpen}>
                            <DialogTrigger asChild>
                              <motion.button
                                onClick={(e) => e.stopPropagation()}
                                className="flex h-6 items-center justify-center rounded-full bg-destructive/10 px-2 text-xs font-medium text-destructive transition-colors hover:bg-destructive/15"
                                whileHover={{ scale: 1.05 }}
                                whileTap={{ scale: 0.95 }}
                              >
                                <span className="text-xs font-medium">untrack</span>
                              </motion.button>
                            </DialogTrigger>
                            <DialogContent className="font-roboto sm:max-w-[425px] border border-border bg-popover text-popover-foreground">
                              <DialogHeader>
                                <DialogTitle className="font-roboto text-foreground">Untrack Competitor</DialogTitle>
                                <DialogDescription className="font-roboto text-muted-foreground">
                                  Are you sure you want to untrack "{current.title}" from your competitors list? This action cannot be undone.
                                </DialogDescription>
                              </DialogHeader>
                              <DialogFooter>
                                <Button
                                  type="button"
                                  variant="outline"
                                  className="font-roboto"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setIsRemoveDialogOpen(false);
                                  }}
                                >
                                  Cancel
                                </Button>
                                <Button
                                  type="button"
                                  className="font-roboto bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    current.onRemove?.();
                                    setIsRemoveDialogOpen(false);
                                    setCurrent(null);
                                    setShowScramble(false);
                                  }}
                                >
                                  Untrack
                                </Button>
                              </DialogFooter>
                            </DialogContent>
                          </Dialog>
                        )}
                      </div>
                      <motion.p
                        layoutId={`cardItemSubtitle-${current.id}`}
                        className="text-sm font-roboto text-primary/70"
                      >
                        {current.subtitle} / {current.description}
                      </motion.p>
                      <motion.div
                        className="flex flex-row gap-2 text-xs font-roboto text-primary/70"
                        layoutId={`cardItemMetadata-${current.id}`}
                      >
                        {current.metadata}
                      </motion.div>
                    </div>
                  </div>
                </div>
                <motion.div
                  layout
                  initial={{ opacity: 0, filter: "blur(5px)" }}
                  animate={{ opacity: 1, filter: "blur(0px)" }}
                  transition={{
                    duration: 0.3,
                    ease: "easeInOut",
                  }}
                  exit={{
                    opacity: 0,
                    transition: { duration: 0.1 },
                    filter: "blur(3px)",
                  }}
                  className="w-full text-sm text-primary/70"
                >
                  <div className="min-h-[1.25rem]">
                    <TextScramble
                      trigger={showScramble}
                      duration={0.7}
                      speed={0.03}
                      className="font-mono text-sm leading-tight"
                      onScrambleComplete={() => setShowScramble(false)}
                    >
                      {current.details}
                    </TextScramble>
                  </div>
                </motion.div>
                {current.extended && current.extended.length > 0 ? (
                  <motion.dl
                    layout
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, ease: "easeOut", delay: 0.08 }}
                    className="grid w-full gap-3 rounded-lg border border-primary/10 bg-primary/5 p-4 text-xs text-primary/60 sm:grid-cols-2"
                  >
                    {current.extended.map((item, idx) => (
                      <div key={`${current.id}-extended-${idx}`} className="flex flex-col gap-1 text-left">
                        <span className="font-roboto">{item.label}</span>
                        <div className="min-h-[1.25rem]">
                          <TextScramble
                            trigger={showScramble}
                            duration={0.9}
                            speed={0.03}
                            className="text-sm font-medium font-mono text-primary"
                            onScrambleComplete={() => setShowScramble(false)}
                          >
                            {item.value}
                          </TextScramble>
                        </div>
                      </div>
                    ))}
                  </motion.dl>
                ) : null}
                {current.link ? (
                  <motion.a
                    layout
                    href={ensureHref(current.link)}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 text-xs font-semibold font-roboto tracking-[0.3em] text-primary/80 hover:text-primary"
                  >
                    Visit profile
                    <span aria-hidden>↗</span>
                  </motion.a>
                ) : null}
              </motion.div>
            </div>
          </>
        ) : null}
      </AnimatePresence>

      <div className={cn("relative flex items-start", className)}>
        <div className="relative grid w-full grid-cols-1 gap-4 sm:grid-cols-2">
          {items.map((item) => (
            <motion.div
              layoutId={`cardItem-${item.id}`}
              key={item.id}
              initial={{ scale: 1 }}
              whileHover={{ scale: 1.02 }}
              className="relative flex cursor-pointer flex-row items-center gap-4 rounded-2xl border border-border bg-card px-4 py-3 shadow-md transition-colors hover:border-primary/40 dark:bg-card/80"
              onClick={(event) => {
                event.stopPropagation();
                setCurrent(item);
                setShowScramble(true);
                item.onExpand?.();
              }}
            >
              {/* Select checkbox - only show when onSelect is provided */}
              {item.onSelect && (
                <div 
                  className="flex items-center"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    checked={item.isSelected || false}
                    onChange={(e) => item.onSelect?.(e.target.checked)}
                    className="h-4 w-4 rounded border-input bg-background text-primary focus:ring-primary focus:ring-2"
                  />
                </div>
              )}
              
              {item.icon && (
                <motion.div layoutId={`cardItemIcon-${item.id}`}>
                  {item.icon}
                </motion.div>
              )}
              <div className="flex w-full flex-col items-start justify-between gap-0.5">
                <motion.div
                  className="font-medium font-roboto text-primary"
                  layoutId={`cardItemTitle-${item.id}`}
                >
                  {item.title}
                </motion.div>
                <motion.div
                  className="text-xs font-roboto text-primary/70"
                  layoutId={`cardItemSubtitle-${item.id}`}
                >
                  {item.subtitle} / {item.description}
                </motion.div>
                <motion.div
                  className="flex flex-row gap-2 text-xs font-roboto text-primary/70"
                  layoutId={`cardItemMetadata-${item.id}`}
                >
                  {item.metadata}
                </motion.div>
              </div>
              {item.isUnread && (
                <div className="absolute top-2 right-2">
                  <div className="h-1.5 w-1.5 rounded-full bg-blue-400"></div>
                </div>
              )}
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}

const useOutsideClick = (callback: () => void) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        callback();
      }
    };

    document.addEventListener("click", handleClick);

    return () => {
      document.removeEventListener("click", handleClick);
    };
  }, [callback]);

  return ref;
};

const ensureHref = (url: string) => (url.startsWith("http") ? url : `https://${url}`);
