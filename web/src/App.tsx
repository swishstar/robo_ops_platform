import { NavLink, Route, Routes } from "react-router-dom";
import { getStoredUser, setStoredUser, UserRole } from "./api/client";
import { FinanceDetailPage } from "./pages/FinanceDetailPage";
import { FinanceQueuePage } from "./pages/FinanceQueuePage";
import { NewVisitPage } from "./pages/NewVisitPage";
import { TimesheetsPage } from "./pages/TimesheetsPage";
import { VisitDetailPage } from "./pages/VisitDetailPage";
import { VisitsPage } from "./pages/VisitsPage";
import { useState } from "react";

const ROLE_EMAILS: Record<UserRole, string> = {
  technician: "field.tech@roboreliance.internal",
  finance_manager: "finance@roboreliance.internal",
  admin: "admin@roboreliance.internal",
};

export function App() {
  const [user, setUser] = useState(getStoredUser());

  function switchRole(role: UserRole) {
    const email = ROLE_EMAILS[role];
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
          <NavLink to="/timesheets">Timesheets</NavLink>
          {(user.role === "finance_manager" || user.role === "admin") && (
            <NavLink to="/finance">Finance</NavLink>
          )}
        </nav>
        <div className="dev-auth">
          <span>
            {user.email} · {user.role}
          </span>
          <button
            type="button"
            className={user.role === "technician" ? "active-role" : undefined}
            onClick={() => switchRole("technician")}
          >
            Tech
          </button>
          <button
            type="button"
            className={user.role === "finance_manager" ? "active-role" : undefined}
            onClick={() => switchRole("finance_manager")}
          >
            Finance
          </button>
          <button
            type="button"
            className={user.role === "admin" ? "active-role" : undefined}
            onClick={() => switchRole("admin")}
          >
            Admin
          </button>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<VisitsPage />} />
          <Route path="/timesheets" element={<TimesheetsPage />} />
          <Route path="/visits/new" element={<NewVisitPage />} />
          <Route path="/visits/:visitId" element={<VisitDetailPage />} />
          <Route path="/finance" element={<FinanceQueuePage />} />
          <Route path="/finance/:ledgerId" element={<FinanceDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
