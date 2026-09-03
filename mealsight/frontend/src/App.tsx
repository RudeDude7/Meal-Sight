import { Route, Routes } from 'react-router-dom'

import { ErrorBoundary } from '@/components/layout/ErrorBoundary'
import { NavShell } from '@/components/layout/NavShell'
import { ActiveSessionProvider } from '@/lib/activeSession'
import { GroceryList } from '@/pages/GroceryList'
import { History } from '@/pages/History'
import { Home } from '@/pages/Home'
import { MealPlan } from '@/pages/MealPlan'
import { Pantry } from '@/pages/Pantry'
import { Preview } from '@/pages/Preview'
import { Profile } from '@/pages/Profile'

export function App() {
  return (
    <ErrorBoundary>
      <ActiveSessionProvider>
        <Routes>
          {/* Not linked from NavShell — exists purely for visual judgment
              of the Ticket/Stamp primitives before they're applied
              anywhere else. Outside the NavShell layout route on purpose,
              so it isn't constrained by the app shell's own content width. */}
          <Route path="preview" element={<Preview />} />
          <Route element={<NavShell />}>
            <Route index element={<Home />} />
            <Route path="pantry" element={<Pantry />} />
            <Route path="meal-plan" element={<MealPlan />} />
            <Route path="grocery-list" element={<GroceryList />} />
            <Route path="history" element={<History />} />
            <Route path="profile" element={<Profile />} />
          </Route>
        </Routes>
      </ActiveSessionProvider>
    </ErrorBoundary>
  )
}
