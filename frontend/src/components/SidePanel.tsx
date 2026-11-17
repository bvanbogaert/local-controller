import type { View } from "../App";
import { texts } from "../texts";

interface Props {
  open: boolean;
  view: View;
  onSelect: (view: View) => void;
}

/** Panneau gauche escamotable : il porte le menu de l'application. */
export function SidePanel({ open, view, onSelect }: Props) {
  return (
    <nav className={open ? "side-panel open" : "side-panel"} aria-hidden={!open}>
      <div className="side-panel-content">
        <div className="menu-section">{texts.menu.configuration}</div>
        <button
          type="button"
          className={view === "configuration-import" ? "menu-entry current" : "menu-entry"}
          tabIndex={open ? 0 : -1}
          onClick={() => onSelect("configuration-import")}
        >
          {texts.menu.importFromResasat}
        </button>
      </div>
    </nav>
  );
}
