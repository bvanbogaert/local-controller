import { useState } from "react";
import { SidePanel } from "./components/SidePanel";
import { texts } from "./texts";
import { ConfigurationImport } from "./views/ConfigurationImport";
import { GridView } from "./views/GridView";

export type View = "grid" | "configuration-import";

export function App() {
  const [view, setView] = useState<View>("grid");
  const [panelOpen, setPanelOpen] = useState(false);

  return (
    <div className="app">
      <SidePanel
        open={panelOpen}
        view={view}
        onSelect={(selected) => {
          setView(selected);
          setPanelOpen(false);
        }}
      />
      <div className="main">
        <header className="topbar">
          <button
            type="button"
            className="menu-button"
            aria-label={panelOpen ? texts.menu.close : texts.menu.open}
            aria-expanded={panelOpen}
            title={panelOpen ? texts.menu.close : texts.menu.open}
            onClick={() => setPanelOpen(!panelOpen)}
          >
            ≡
          </button>
          <span className="topbar-title">
            {view === "grid" ? texts.grid.title : texts.import.title}
          </span>
        </header>
        <main className="content">
          {view === "grid" ? (
            <GridView />
          ) : (
            <ConfigurationImport onFinish={() => setView("grid")} />
          )}
        </main>
      </div>
    </div>
  );
}
