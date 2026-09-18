import { NavLink, Route, Routes } from "react-router-dom";
import { ApiSettings } from "./components/ApiSettings";
import { JobsPage } from "./pages/JobsPage";
import { SourceStatusPage } from "./pages/SourceStatusPage";
import "./App.css";

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Job Fetching Service</h1>
        <nav>
          <NavLink to="/" end>
            Jobs
          </NavLink>
          <NavLink to="/sources">Source Status</NavLink>
        </nav>
      </header>

      <ApiSettings />

      <main>
        <Routes>
          <Route path="/" element={<JobsPage />} />
          <Route path="/sources" element={<SourceStatusPage />} />
        </Routes>
      </main>
    </div>
  );
}
