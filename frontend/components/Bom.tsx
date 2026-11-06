"use client";

/**
 * Bom - bill of materials for the current assembly.
 *
 * One physical part per instance, so a component repeated eight times counts
 * eight. Read-only: quantities come from the specification, not the viewer.
 */
import { bomRows } from "@/lib/assembly";
import type { DocumentSpecification } from "@/types/api";

interface BomProps {
  spec: DocumentSpecification;
}

export function Bom({ spec }: BomProps) {
  const rows = bomRows(spec);
  if (rows.length === 0) return null;
  const total = rows.reduce((sum, row) => sum + row.quantity, 0);
  return (
    <section className="inspector-section" data-testid="bom">
      <div className="inspector-label">
        Bill of materials · {total} {total === 1 ? "part" : "parts"}
      </div>
      <table className="bom-table">
        <thead>
          <tr>
            <th scope="col">Part</th>
            <th scope="col">Type</th>
            <th scope="col" className="bom-qty">
              Qty
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.type}>
              <td>{row.label}</td>
              <td className="mono bom-type">{row.type}</td>
              <td className="mono bom-qty">{row.quantity}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
