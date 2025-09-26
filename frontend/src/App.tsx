import { useState, useEffect, type ReactNode } from 'react'
import { ImageCombiner } from '@/components/image-combiner'
import { LoginPage } from '@/components/login-page'
import { ThemeProvider } from '@/components/theme-provider'

type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated'

function App() {
  const shouldBypassAuth = (import.meta.env.VITE_BYPASS_AUTH ?? '').toLowerCase() === 'true'
  const [authStatus, setAuthStatus] = useState<AuthStatus>(
    shouldBypassAuth ? 'authenticated' : 'checking'
  )
  const [showLogin, setShowLogin] = useState(false)

  const updateAuthQuery = (shouldShowLogin: boolean) => {
    if (typeof window === 'undefined') {
      return
    }

    const params = new URLSearchParams(window.location.search)
    if (shouldShowLogin) {
      params.set('auth', 'login')
    } else {
      params.delete('auth')
    }
    const query = params.toString()
    const nextUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname
    window.history.replaceState({}, document.title, nextUrl)
  }

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    const params = new URLSearchParams(window.location.search)
    if (params.get('auth') === 'login') {
      setShowLogin(true)
    }
  }, [])

  useEffect(() => {
    if (shouldBypassAuth) {
      return
    }

    let isActive = true
    const cleanup = () => {
      isActive = false
    }

    // 检查URL中的token（OAuth回调）
    const urlParams = new URLSearchParams(window.location.search)
    const token = urlParams.get('token')

    if (token) {
      localStorage.setItem('auth_token', token)
      window.history.replaceState({}, document.title, window.location.pathname)
      if (isActive) {
        setAuthStatus('authenticated')
      }
      return cleanup
    }

    const existingToken = localStorage.getItem('auth_token')

    if (!existingToken) {
      if (isActive) {
        setAuthStatus('unauthenticated')
      }
      return cleanup
    }

    const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

    const verifyToken = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/auth/me`, {
          headers: {
            Authorization: `Bearer ${existingToken}`,
          },
        })

        if (!response.ok) {
          throw new Error('Token verification failed')
        }

        if (isActive) {
          setAuthStatus('authenticated')
        }
      } catch (err) {
        console.error('Failed to verify auth token', err)
        localStorage.removeItem('auth_token')
        if (isActive) {
          setAuthStatus('unauthenticated')
        }
      }
    }

    verifyToken()

    return cleanup
  }, [shouldBypassAuth])

  useEffect(() => {
    if (authStatus === 'authenticated') {
      setShowLogin(false)
      updateAuthQuery(false)
    }
  }, [authStatus])

  let content: ReactNode

  if (authStatus === 'checking') {
    content = (
      <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
        正在验证登录状态...
      </div>
    )
  } else if (showLogin) {
    content = (
      <LoginPage
        onBack={() => {
          setShowLogin(false)
          updateAuthQuery(false)
        }}
      />
    )
  } else {
    content = (
      <ImageCombiner
        onRequestAuth={() => {
          setShowLogin(true)
          updateAuthQuery(true)
        }}
      />
    )
  }

  return (
    <ThemeProvider defaultTheme="system" storageKey="opp-agent-ui-theme">
      {content}
    </ThemeProvider>
  )
}

export default App
