"use client";

import { useMemo, useState } from "react";
import type { CatalogComponent, ComponentCategory } from "@/types/api";

const CATEGORIES: { id: ComponentCategory; label: string }[] = [
  { id: "geometry", label: "Geometry" },
  { id: "fasteners", label: "Fasteners" },
  { id: "mechanical", label: "Mechanical" },
  { id: "electronics", label: "Electronics" },
  { id: "templates", label: "Templates" },
];

interface ComponentBrowserProps {
  catalog: CatalogComponent[];
  busy: boolean;
  onAdd: (type: string, count?: number) => void;
}

export function ComponentBrowser({ catalog, busy, onAdd }: ComponentBrowserProps) {
  const [open, setOpen] = useState<ComponentCategory | null>("geometry");
  const grouped = useMemo(() => {
    const map = new Map<ComponentCategory, CatalogComponent[]>();
    for (const item of catalog) {
      if (!item.insertable) continue;
      const list = map.get(item.category) ?? [];
      list.push(item);
      map.set(item.category, list);
    }
    return map;
  }, [catalog]);

  return (
    <section className="inspector-section" data-testid="component-browser">
      <div className="inspector-label">Components</div>
      <p className="browser-hint">Add from the library — no AI required.</p>
      {CATEGORIES.map((cat) => {
        const items = grouped.get(cat.id) ?? [];
        if (items.length === 0) return null;
        const expanded = open === cat.id;
        return (
          <div key={cat.id} className="browser-cat">
            <button
              type="button"
              className="browser-cat-toggle"
              onClick={() => setOpen(expanded ? null : cat.id)}
              aria-expanded={expanded}
            >
              {cat.label}
              <span className="browser-count">{items.length}</span>
            </button>
            {expanded ? (
              <ul className="browser-list">
                {items.map((item) => (
                  <li key={item.type} className="browser-row">
                    <div>
                      <div className="browser-name">{item.display_name}</div>
                      <div className="browser-desc">{item.description}</div>
                    </div>
                    <button
                      type="button"
                      className="browser-add"
                      disabled={busy}
                      onClick={() =>
                        onAdd(item.type, item.type === "m3_screw" ? 1 : 1)
                      }
                    >
                      Add
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
