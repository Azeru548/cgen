"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
 *
 * The open panel is portaled to document.body with fixed positioning: the
 * rail scrolls (overflow:auto), which would clip an absolutely-positioned
 * flyout and paint it under the WebGL canvas. The portal escapes both.
 */
export function ComponentBrowser({ catalog, busy, onAdd }: ComponentBrowserProps) {
  const [open, setOpen] = useState<ComponentCategory | null>(null);
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null);
  const rootRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const toggleRefs = useRef(new Map<ComponentCategory, HTMLButtonElement | null>());

  const openCategory = (cat: ComponentCategory) => {
    if (open === cat) {
      setOpen(null);
      setAnchor(null);
      return;
    }
    const rect = toggleRefs.current.get(cat)?.getBoundingClientRect();
    if (rect) {
      const width = Math.min(320, window.innerWidth - 40);
      setAnchor({
        top: Math.max(8, Math.min(rect.top, window.innerHeight - 160)),
        left: Math.max(8, Math.min(rect.right + 7, window.innerWidth - width - 8)),
      });
    } else {
      setAnchor(null);
    }
    setOpen(cat);
  };

  useEffect(() => {
    if (open === null) return undefined;
    const close = () => {
      setOpen(null);
      setAnchor(null);
    };
    const onPointer = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !panelRef.current?.contains(target)) {
        close();
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open ]);

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
                ref={(node) => {
                  toggleRefs.current.set(cat.id, node);
                }}
                className="palette-toggle"
                aria-expanded={expanded}
                aria-controls={`palette-panel-${cat.id}`}
                onClick={() => openCategory(cat.id)}
              >
                <span className="palette-toggle-label">{cat.label}</span>
                <span className="palette-toggle-mark" aria-hidden="true">
                  {expanded ? "−" : "+"}
                </span>
              </button>
              {expanded && anchor
                ? createPortal(
                    <div
                      id={`palette-panel-${cat.id}`}
                      ref={panelRef}
                      className="palette-panel palette-panel-floating"
                      role="region"
                      aria-label={`${cat.label} components`}
                      style={{ top: anchor.top, left: anchor.left }}
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
                    </div>,
                    document.body,
                  )
                : null}
            </div>
          );
        })}
      </div>
    </nav>
  );
}
