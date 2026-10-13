const publicActions = new Set(['list_meet_posts','meet_post_count','get_meet_post','get_public_meet_contact']);
const userActions = new Set(['get_meet_contact','submit_meet_post','withdraw_meet_post']);

export function requestAction(value: unknown): { action: string; params: Record<string,unknown>; needsUser: boolean } {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid_request');
  const input = value as Record<string,unknown>;
  if (typeof input.action !== 'string' || (!publicActions.has(input.action) && !userActions.has(input.action))) throw new Error('invalid_request');
  if (input.params != null && (typeof input.params !== 'object' || Array.isArray(input.params))) throw new Error('invalid_request');
  return { action: input.action, params: (input.params || {}) as Record<string,unknown>, needsUser: userActions.has(input.action) };
}

export function requestFailure(error: unknown) {
  const invalid=error instanceof SyntaxError || (error instanceof Error && error.message==='invalid_request');
  return invalid
    ? {status:400,error:{code:'22023',message:'Invalid request'}}
    : {status:503,error:{code:'503',message:'Community service unavailable'}};
}
