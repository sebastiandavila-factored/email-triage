// Where a pending invite token is stashed while the invitee logs in or signs up,
// then re-consumed by /accept-invite once authenticated.
export const PENDING_INVITE_KEY = 'pending_invite'

// Post-authentication destination: a pending invite takes priority so the
// invitee lands on /accept-invite (which consumes it) rather than the dashboard.
export function nextAfterAuth(): string {
  return sessionStorage.getItem(PENDING_INVITE_KEY) ? '/accept-invite' : '/dashboard'
}
