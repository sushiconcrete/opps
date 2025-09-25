// src/components/login-page.tsx - 简化版本，移除AuthContext依赖
import { useState, useEffect } from "react"
import { AnimatedBackground } from "@/components/animated-background"
import { Button } from "@/components/ui/button"
import { ModeToggle } from "@/components/mode-toggle"

export function LoginPage() {
  const [loadingState, setLoadingState] = useState({ google: false, github: false })
  const [error, setError] = useState<string>("")
  const [successMessage, setSuccessMessage] = useState<string>("")

  useEffect(() => {
    // 检查是否有错误参数
    const urlParams = new URLSearchParams(window.location.search)
    const errorParam = urlParams.get('error')
    const successParam = urlParams.get('success')

    if (errorParam) {
      setError(decodeURIComponent(errorParam))
      // 清理URL参数
      window.history.replaceState({}, document.title, window.location.pathname)
    }

    if (successParam) {
      setSuccessMessage(decodeURIComponent(successParam))
      // 清理URL参数
      window.history.replaceState({}, document.title, window.location.pathname)
    }
  }, [])

  const handleGoogleLogin = () => {
    setLoadingState({ google: true, github: false })
    setError('')
    setSuccessMessage('')
    
    // 重定向到后端的Google OAuth端点
    const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
    window.location.href = `${apiBaseUrl}/api/auth/google`
  }

  const handleGithubLogin = () => {
    setLoadingState({ google: false, github: true })
    setError('')
    setSuccessMessage('')
    
    // 重定向到后端的GitHub OAuth端点
    const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
    window.location.href = `${apiBaseUrl}/api/auth/github`
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-6 text-foreground">
      <AnimatedBackground />
      <div className="absolute right-6 top-6 z-20">
        <ModeToggle />
      </div>

      <div className="relative z-10 flex w-full max-w-md flex-col items-center gap-6 text-center">
        {/* OPP Brand */}
        <span className="text-5xl font-semibold tracking-[0.35em] text-foreground">opp</span>
        
        {/* Welcome Message */}
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold text-foreground">
            Welcome back
          </h1>
          <p className="text-sm text-muted-foreground">
            Sign in to access your competitive intelligence dashboard
          </p>
        </div>

        {/* Login Form */}
        <div className="w-full space-y-4 rounded-2xl border border-border bg-card p-6 text-left shadow-[0_25px_60px_-20px_rgba(0,0,0,0.35)] backdrop-blur">
          
          {/* Success Message */}
          {successMessage && (
            <div className="rounded-lg border border-green-500/40 bg-green-500/10 px-4 py-3 text-xs text-green-200">
              {successMessage}
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-xs text-red-200">
              {error}
            </div>
          )}

          {/* Login Buttons */}
          <div className="space-y-3">
            <Button
              onClick={handleGoogleLogin}
              disabled={loadingState.google || loadingState.github}
              isLoading={loadingState.google}
              loadingText="Connecting..."
              className="h-12 w-full rounded-xl bg-gradient-to-br from-primary via-primary/90 to-primary/70 text-sm font-semibold text-primary-foreground shadow-[0_12px_35px_rgba(0,0,0,0.35)] transition hover:from-primary/90 hover:to-primary/60"
            >
              <div className="flex items-center justify-center gap-3">
                <svg className="h-5 w-5" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                </svg>
                <span>Continue with Google</span>
              </div>
            </Button>

            <Button
              onClick={handleGithubLogin}
              disabled={loadingState.google || loadingState.github}
              isLoading={loadingState.github}
              loadingText="Connecting..."
              className="h-12 w-full rounded-xl bg-gradient-to-br from-slate-900 via-slate-800 to-slate-700 text-sm font-semibold text-white shadow-[0_12px_35px_rgba(0,0,0,0.35)] transition hover:from-slate-800 hover:to-slate-600 dark:from-slate-200 dark:via-slate-100 dark:to-white dark:text-slate-900"
            >
              <div className="flex items-center justify-center gap-3">
                <svg className="h-5 w-5 fill-current" viewBox="0 0 24 24">
                  <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                </svg>
                <span>Continue with GitHub</span>
              </div>
            </Button>
          </div>
        </div>

        {/* Footer */}
        <p className="text-xs text-muted-foreground">
          By continuing, you agree to our{" "}
          <span className="text-foreground underline underline-offset-2">Terms</span> and{" "}
          <span className="text-foreground underline underline-offset-2">Privacy Policy</span>
        </p>
      </div>
    </div>
  )
}
