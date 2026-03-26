"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";

type Props = {
  projectName?: string;
  entities?: string[];
};

const FIELD_TYPES = ["string", "int", "float", "bool", "datetime"];

export default function AddFieldCard({ projectName, entities }: Props) {
  const router = useRouter();
  const entityOptions = useMemo(() => {
    const rows = Array.isArray(entities) ? entities : [];
    return rows
      .map((item) => String(item || "").trim())
      .filter((item) => item.length > 0);
  }, [entities]);
  const [entityName, setEntityName] = useState(entityOptions[0] || "");
  const [fieldName, setFieldName] = useState("");
  const [fieldType, setFieldType] = useState("string");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetProject = String(projectName || "").trim();
    const targetEntity = String(entityName || "").trim();
    const targetFieldName = String(fieldName || "").trim();
    const targetFieldType = String(fieldType || "").trim();
    if (!targetProject) {
      setError("Failed to add field: project name is missing");
      return;
    }
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(targetProject)}/fields`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_name: targetEntity,
          field_name: targetFieldName,
          field_type: targetFieldType,
        }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
        entity_name?: string;
        field_name?: string;
        field_type?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const detail = String(payload.error || payload.detail || "").trim();
        setError(detail ? `Failed to add field: ${detail}` : "Failed to add field");
        return;
      }
      const updatedEntity = String(payload.entity_name || targetEntity).trim();
      const updatedFieldName = String(payload.field_name || targetFieldName).trim();
      const updatedFieldType = String(payload.field_type || targetFieldType).trim();
      setFieldName("");
      setSuccess(
        updatedEntity && updatedFieldName && updatedFieldType
          ? `Field added: ${updatedEntity}.${updatedFieldName}:${updatedFieldType}`
          : "Field added"
      );
      router.refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e || "unknown error");
      setError(`Failed to add field: ${message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Add Field</h3>
      {!entityOptions.length ? (
        <p className="mt-3 text-xs text-slate-300">No entities found. Add an entity first.</p>
      ) : null}
      <form onSubmit={onSubmit} className="mt-3 grid gap-2 sm:grid-cols-4">
        <select
          value={entityName}
          onChange={(event) => setEntityName(event.target.value)}
          disabled={!entityOptions.length || loading}
          className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100"
        >
          {entityOptions.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={fieldName}
          onChange={(event) => setFieldName(event.target.value)}
          placeholder="Field name (e.g. priority)"
          disabled={!entityOptions.length || loading}
          className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-400"
        />
        <select
          value={fieldType}
          onChange={(event) => setFieldType(event.target.value)}
          disabled={!entityOptions.length || loading}
          className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100"
        >
          {FIELD_TYPES.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={!entityOptions.length || loading}
          className="rounded-md border border-cyan-600 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
        >
          {loading ? "Adding..." : "Add Field"}
        </button>
      </form>
      {error ? <p className="mt-2 break-words text-xs text-rose-300">{error}</p> : null}
      {!error && success ? <p className="mt-2 break-words text-xs text-emerald-300">{success}</p> : null}
    </section>
  );
}
