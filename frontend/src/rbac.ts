// Mirror of the backend ROLE_SCOPES — used ONLY to show/hide UI affordances.
// The backend re-checks every request; this is convenience, never security.
export const FRONT_ROLE_SCOPES: Record<string, string[]> = {
  owner: ['triage:write', 'workspace:manage', 'workspace:delete'],
  admin: ['triage:write', 'workspace:manage'],
  member: ['triage:write'],
}

export function can(role: string | undefined, scope: string): boolean {
  if (!role) return false
  return FRONT_ROLE_SCOPES[role]?.includes(scope) ?? false
}
