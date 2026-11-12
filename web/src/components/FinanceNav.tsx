import { NavLink } from "react-router-dom";

export function FinanceNav() {
  return (
    <nav className="subnav" aria-label="Finance">
      <NavLink to="/finance" end>
        Queue
      </NavLink>
      <NavLink to="/finance/progress">Payment progress</NavLink>
      <NavLink to="/finance/settings">Settings</NavLink>
    </nav>
  );
}
