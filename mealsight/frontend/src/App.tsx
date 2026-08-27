import { Route, Routes } from 'react-router-dom'

import { ErrorBoundary } from '@/components/layout/ErrorBoundary'
import { NavShell } from '@/components/layout/NavShell'
import { Home } from '@/pages/Home'
import { Pantry } from '@/pages/Pantry'
import { Profile } from '@/pages/Profile'

export function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<NavShell />}>
          <Route index element={<Home />} />
          <Route path="pantry" element={<Pantry />} />
          <Route path="profile" element={<Profile />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  )
}
