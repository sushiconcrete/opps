import * as React from 'react'

import { cn } from '@/lib/utils'

type InputVariant = 'default' | 'ghost'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  variant?: InputVariant
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = 'text', variant = 'default', ...props }, ref) => {
    const variantClasses: Record<InputVariant, string> = {
      default:
        'border border-input bg-card px-4 shadow-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background dark:bg-card/70',
      ghost:
        'border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0',
    }

    return (
      <input
        type={type}
        className={cn(
          'flex h-12 w-full rounded-md text-base text-foreground placeholder:text-muted-foreground transition-colors disabled:cursor-not-allowed disabled:opacity-50',
          'ring-offset-background focus-visible:outline-none',
          variantClasses[variant],
          className,
        )}
        ref={ref}
        {...props}
      />
    )
  },
)

Input.displayName = 'Input'

export { Input }
