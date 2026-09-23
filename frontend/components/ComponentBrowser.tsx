"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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

/**
 * Component library palette — horizontal category dropdowns above the
 * workspace body. Opening a category overlays content so the shell height
 * never grows. Only one category is open at a time.
 */
export function ComponentBrowser({ catalog, busy, onAdd }: ComponentBrowserProps) {
  const [open, setOpen] = useState<ComponentCategory | null>(null);
  const rootRef = useRef<HTMLElement | null>(null);

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

  useEffect(() => {
    if (open === null) return undefined;
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(null);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <nav
      ref={rootRef}
      className="palette"
      aria-label="Component library"
      data-testid="component-browser"
    >
      <span className="palette-label">Model library</span>
      <div className="palette-cats">
        {CATEGORIES.map((cat) => {
          const items = grouped.get(cat.id) ?? [];
          if (items.length === 0) return null;
          const expanded = open === cat.id;
          return (
            <div
              key={cat.id}
              className={`palette-cat${expanded ? " open" : ""}`}
            >
              <button
                type="button"
                className="palette-toggle"
                aria-expanded={expanded}
                aria-controls={`palette-panel-${cat.id}`}
                onClick={() => setOpen(expanded ? null : cat.id)}
              >
                <span className="palette-toggle-label">{cat.label}</span>
                <span className="palette-toggle-mark" aria-hidden="true">
                  {expanded ? "−" : "+"}
                </span>
              </button>
              <div
                id={`palette-panel-${cat.id}`}
                className="palette-panel"
                role="region"
                aria-label={`${cat.label} components`}
                hidden={!expanded}
              >
                <div className="palette-panel-inner">
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
                          onClick={() => onAdd(item.type, 1)}
                        >
                          Add
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </nav>
  );
}
