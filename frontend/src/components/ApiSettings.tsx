import { useState } from "react";
import { getApiKey, getBaseUrl, setApiKey, setBaseUrl } from "../api/client";
import "./ApiSettings.css";

export function ApiSettings() {
  const [baseUrl, setBaseUrlState] = useState(getBaseUrl());
  const [apiKey, setApiKeyState] = useState(getApiKey());
  const [open, setOpen] = useState(false);

  const save = () => {
    setBaseUrl(baseUrl);
    setApiKey(apiKey);
    window.location.reload();
  };

  return (
    <div className="api-settings">
      <button type="button" className="api-settings-toggle" onClick={() => setOpen((o) => !o)}>
        API settings {open ? "▲" : "▼"}
      </button>
      {open && (
        <div className="api-settings-panel">
          <label>
            Backend URL
            <input value={baseUrl} onChange={(e) => setBaseUrlState(e.target.value)} />
          </label>
          <label>
            API key
            <input value={apiKey} onChange={(e) => setApiKeyState(e.target.value)} />
          </label>
          <button type="button" onClick={save}>
            Save &amp; reload
          </button>
        </div>
      )}
    </div>
  );
}
