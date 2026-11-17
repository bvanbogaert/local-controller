// Dialogue avec le backend (README.d/backend.md).

export type Period = "active" | "all";
export type Origin = "resasat" | "all";

export interface Field {
  label: string;
  value: string;
}

/** Enregistrement ajouté ou supprimé : une case à cocher, désignée par key. */
export interface RecordChange {
  key: string;
  id: number;
  label: string;
  fields: Field[];
}

/** Champ modifié : une case à cocher, désignée par key. */
export interface FieldChange {
  key: string;
  label: string;
  old: string;
  new: string;
}

export interface RecordUpdate {
  id: number;
  label: string;
  fields: FieldChange[];
}

export interface TableComparison {
  name: string;
  label: string;
  in_file: boolean;
  ignored_columns: string[];
  discarded: number;
  invalid: { id: number; reason: string }[];
  inserts: RecordChange[];
  updates: RecordUpdate[];
  deletes: RecordChange[];
}

export interface Comparison {
  token: string;
  period: Period;
  origin: Origin;
  reference_time: number;
  file_date: number | null;
  tables: TableComparison[];
  ignored_tables: { name: string; label: string; reason: string }[];
  total: number;
}

export interface Report {
  tables: { name: string; label: string; insert: number; update: number; delete: number }[];
  ignored: number;
}

const BASE = "/api/configuration/import";

/** Le backend répond toujours {"detail": message} en cas d'erreur. */
async function read<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
  }
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      message = body.detail;
    }
  } catch {
    // réponse sans JSON : le code HTTP suffit
  }
  throw new Error(message);
}

export async function uploadConfiguration(
  file: File,
  period: Period,
  origin: Origin,
): Promise<Comparison> {
  const form = new FormData();
  form.append("file", file);
  form.append("period", period);
  form.append("origin", origin);
  return read(await fetch(BASE, { method: "POST", body: form }));
}

/** La sélection ne transporte que des clés : les valeurs restent côté serveur. */
export async function applyConfiguration(token: string, selection: string[]): Promise<Report> {
  return read(
    await fetch(`${BASE}/${encodeURIComponent(token)}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selection }),
    }),
  );
}

export async function cancelConfiguration(token: string): Promise<void> {
  return read(await fetch(`${BASE}/${encodeURIComponent(token)}`, { method: "DELETE" }));
}
