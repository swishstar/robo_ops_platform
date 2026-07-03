import { NavLink, Route, Routes } from "react-router-dom";
import { getStoredUser, setStoredUser, UserRole } from "./api/client";
import { FinanceDetailPage } from "./pages/FinanceDetailPage";
import { FinanceQueuePage } from "./pages/FinanceQueuePage";
import { NewVisitPage } from "./pages/NewVisitPage";
import { VisitDetailPage } from "./pages/VisitDetailPage";
import { VisitsPage } from "./pages/VisitsPage";
import { useState } from "react";

export function App() {
  const [user, setUser] = useState(getStoredUser());

  function switchRole(role: UserRole) {
    const email =
      role === "finance_manager"
        ? "finance@roboreliance.internal"
        : "field.tech@roboreliance.internal";
    setStoredUser(email, role);
    setUser({ email, role });
  }

  return (
    <div className="app">
      <header>
        <h1>Robo Reliance Ops</h1>
        <nav>
          <NavLink to="/" end>
            Visits
          </NavLink>
          {(user.role === "finance_manager" || user.role === "admin") && (
            <NavLink to="/finance">Finance</NavLink>
          )}
        </nav>
        <div className="dev-auth">
          <span>{user.email}</span>
          <button type="button" onClick={() => switchRole("technician")}>
            Tech
          </button>
          <button type="button" onClick={() => switchRole("finance_manager")}>
            Finance
          </button>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<VisitsPage />} />
          <Route path="/visits/new" element={<NewVisitPage />} />
          <Route path="/visits/:visitId" element={<VisitDetailPage />} />
          <Route path="/finance" element={<FinanceQueuePage />} />
          <Route path="/finance/:ledgerId" element={<FinanceDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
