"""Read-only queue progress; unsubmitted staged videos are never called queued."""
from collections import Counter

PROCESSING={'recognizing','extracting','transcribing','organizing'}
WRITING={'publishing','refreshing'}
QUEUED={'queued','publish_queued','refresh_queued'}
FAILED={'failed','interrupted','publish_failed','refresh_failed'}
REVIEW={'publish_uncertain','refresh_uncertain'}

def progress_snapshot(store,folder_import):
    with store.lock:
        jobs=store.visible_list();counts=Counter(j['status'] for j in jobs);pending=folder_import.pending()
        active=[{k:j[k] for k in ('id','name','status','detail')} for j in jobs if j['status'] in PROCESSING|WRITING]
        return {'total':len(jobs),'queued':sum(counts[s] for s in QUEUED),'processing':sum(counts[s] for s in PROCESSING),'writing':sum(counts[s] for s in WRITING),'published':counts['published'],'ready':counts['ready'],'failed':sum(counts[s] for s in FAILED),'needs_manual':counts['needs_manual'],'needs_review':sum(counts[s] for s in REVIEW),'text_ready':sum((store.root/'jobs'/j['id']/'result.json').is_file() for j in jobs),'settled':sum(j['status'] not in PROCESSING|WRITING|QUEUED for j in jobs),'pending':len(pending),'pending_matches':sum(bool(i['matches']) for i in pending),'pending_new':sum(not i['matches'] for i in pending),'active':active}
