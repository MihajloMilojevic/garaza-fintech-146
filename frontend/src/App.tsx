import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Accounts } from './pages/Accounts'
import { AccountDetailPage } from './pages/AccountDetail'
import { ScreeningQueue } from './pages/ScreeningQueue'
import { LiveScreener } from './pages/LiveScreener'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="accounts/:id" element={<AccountDetailPage />} />
          <Route path="queue" element={<ScreeningQueue />} />
          <Route path="screener" element={<LiveScreener />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
