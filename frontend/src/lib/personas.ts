export type Persona = { id: string; tenant: string; group: string; label: string };

export const PERSONAS: Persona[] = [
  { id: "t1-eng", tenant: "tenant-1", group: "eng", label: "Tenant 1 · Engineering" },
  { id: "t1-hr", tenant: "tenant-1", group: "hr", label: "Tenant 1 · HR" },
  { id: "t1-fin", tenant: "tenant-1", group: "fin", label: "Tenant 1 · Finance" },
  { id: "t2-eng", tenant: "tenant-2", group: "eng", label: "Tenant 2 · Engineering" },
  { id: "t3-hr", tenant: "tenant-3", group: "hr", label: "Tenant 3 · HR" },
];

export const DEFAULT_PERSONA_ID = "t1-eng";

export function findPersona(id: string | undefined): Persona | undefined {
  return PERSONAS.find((p) => p.id === id);
}

export const TENANTS = ["tenant-1", "tenant-2", "tenant-3"];
export const GROUPS = ["eng", "hr", "fin"];


