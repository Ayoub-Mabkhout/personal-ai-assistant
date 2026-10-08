"""Keep native Assist pipelines behind programmed-first/default-Luna dispatch."""

DISPATCH_ENGINE = 'conversation.assistant_dispatch'
NATIVE_ENGINES = {'home_assistant', 'conversation.home_assistant'}


def dispatch_updates(pipelines):
    updates = []
    for pipeline in pipelines:
        engine = pipeline.get('conversation_engine')
        if engine not in NATIVE_ENGINES | {DISPATCH_ENGINE}:
            continue
        if engine == DISPATCH_ENGINE and pipeline.get('prefer_local_intents') is False:
            continue
        settings = {key: value for key, value in pipeline.items() if key != 'id'}
        settings.update(conversation_engine=DISPATCH_ENGINE, prefer_local_intents=False)
        updates.append({'type': 'assist_pipeline/pipeline/update',
                        'pipeline_id': pipeline['id'], **settings})
    return updates
