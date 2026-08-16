import { useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './supabaseClient'

interface SessionAdminState {
  isAdmin: boolean
  loading: boolean
  email: string | null
}

export function useIsAdmin(): SessionAdminState {
  const [state, setState] = useState<SessionAdminState>({ isAdmin: false, loading: true, email: null })

  useEffect(() => {
    let active = true
    const read = (session: Session | null) => {
      if (!active) return
      setState({
        isAdmin: session?.user?.app_metadata?.role === 'admin',
        loading: false,
        email: session?.user?.email ?? null,
      })
    }
    supabase.auth.getSession().then(({ data }) => read(data.session))
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => read(session))
    return () => {
      active = false
      sub.subscription.unsubscribe()
    }
  }, [])

  return state
}
