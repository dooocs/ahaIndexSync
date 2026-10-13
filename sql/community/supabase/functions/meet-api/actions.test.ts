import { requestAction, requestFailure } from './actions.ts';

Deno.test('public projections and user writes are explicitly allowlisted',()=>{
  for (const action of ['list_meet_posts','meet_post_count','get_meet_post','get_public_meet_contact']) {
    if (requestAction({action}).needsUser) throw new Error('Public action requires a user');
  }
  for (const action of ['submit_meet_post','withdraw_meet_post','get_meet_contact']) {
    if (!requestAction({action}).needsUser) throw new Error('Private action lacks auth');
  }
});
Deno.test('service failures are not reported as invalid user input or reflected in responses',()=>{
  for(const error of [new SyntaxError('private-request-body'),new Error('invalid_request')]) {
    if(requestFailure(error).status!==400) throw new Error('Malformed request accepted');
  }
  const result=requestFailure(new Error('private-token-and-database-error'));
  if(result.status!==503 || JSON.stringify(result).includes('private-token')) throw new Error('Internal failure reflected');
});
Deno.test('review, raw photo rows, cleanup and arbitrary RPCs cannot be dispatched',()=>{
  for (const action of ['list_meet_photos','review_meet_post','meet_api','configure_meet_photo_cleanup','submit_meet_post_text','get_meet_review_post']) {
    let denied=false; try { requestAction({action}); } catch { denied=true; }
    if (!denied) throw new Error(`Allowed private action: ${action}`);
  }
  for (const value of [null,[],{action:'submit_meet_post',params:[]}]) {
    let denied=false; try { requestAction(value); } catch { denied=true; }
    if (!denied) throw new Error('Invalid request accepted');
  }
});
