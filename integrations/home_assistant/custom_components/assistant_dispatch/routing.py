"""Unmatched speech/targets fall through; attempted programmed actions stay handled."""
def should_dispatch(error_code,success_results=(),failed_results=()):
    if success_results or failed_results:
        return False
    return getattr(error_code,'value',error_code) in {'no_intent_match','no_valid_targets'}


def acknowledgement(body):
    job=body['job'];state=job['state']
    if state!='queued':return 'That request is '+state.replace('_',' ')+'. Task '+job['id'][-8:]+'.'
    if body['connection']['laptop']=='ready':message='Queued for the laptop.'
    else:message='Saved on the server. Waiting for the laptop.'
    if body.get('notifications',{}).get('enabled'):message+=' Your phone will receive updates.'
    return message+' Task '+job['id'][-8:]+'.'
