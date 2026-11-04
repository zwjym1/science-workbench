"""Pure, conservative normalization of batch20 capture rows.

Only allowlisted public fields are returned. Raw payloads belong in the evidence
store, not this model. Presence of a target_identified flag is never proof of ID.
"""
import re
from .models import CommentCollection


def _text(value):
    if not isinstance(value, str):
        return None
    return re.sub(r'https?://[^\s<>"\x27]+', '[redacted_url]', value)


def _id(value):
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else None


def _refs(page, keys):
    refs = page.get('references') or {}
    ids = []
    for key in keys:
        values = refs.get(key, [])
        if not isinstance(values, list):
            values = [values]
        ids.extend(_id(v) for v in values)
    return ids


def _owned(page, video):
    values = _refs(page, ('aweme_id', 'item_id', 'from_group_id'))
    return bool(values) and all(v == video for v in values)


def _state(collection, gate, hint=None):
    if hint=='observed_empty' and not collection.items and not gate:
        collection.status='observed_empty';collection.stop_reason='no_replies_in_exhausted_comments'
    elif gate or hint in ('blocked_login','blocked_verification','error','not_requested'):
        collection.status = hint if hint in ('blocked_login','blocked_verification','error','not_requested') else 'blocked_login'
        collection.stop_reason = collection.status
    elif hint == 'partial' or collection.stop_reason in ('rejected_attribution','limit_reached'):
        collection.status = 'partial'
    elif not collection.pages:
        collection.status = 'partial' if collection.items else 'missing'
    elif collection.has_more is not False:
        collection.status = 'partial'
        collection.stop_reason = 'has_more' if collection.has_more else 'pagination_unknown'
    else:
        collection.status = 'available' if collection.items else 'observed_empty'
        collection.stop_reason = 'exhausted'
    collection.unique_count = len(collection.items)
    return collection.to_dict()


def normalize_capture(row: dict) -> dict:
    """Return a new public result; reject ambiguous/conflicting attribution.

    Nested suggest snapshots in batch20 are pre-associated with the row's target.
    Independent suggest endpoints remain separate even with matching request IDs.
    """
    video = _id(row.get('video_id'))
    if not video:
        raise ValueError('video_id is required')
    rejected = []
    detail = row.get('detail') or {}
    valid_detail = isinstance(detail, dict) and _id(detail.get('aweme_id')) == video
    public_detail = {'status':'missing'}
    if valid_detail:
        public_detail = {'status':'available','video_id':video,
                         'description':_text(detail.get('desc')), 'create_time':detail.get('create_time') if isinstance(detail.get('create_time'),int) else None,
                         'duration_ms':detail.get('duration') if isinstance(detail.get('duration'),int) else None,
                         'author':{k:_text((detail.get('author') or {}).get(k)) for k in ('uid','nickname')},
                         'statistics':{k:v for k,v in (detail.get('statistics') or {}).items() if k in ('digg_count','comment_count','collect_count','share_count','play_count') and isinstance(v,int)}}
    elif detail:
        rejected.append({'kind':'detail','reason':'video_mismatch_or_missing'})
    if not valid_detail and row.get('detail_status') in ('error','blocked_verification','blocked_login'):
        public_detail['status']=row['detail_status']
    roots, replies = {}, {}
    root_collection, reply_collection = CommentCollection(), CommentCollection()
    reply_parent_totals={}

    def add(item, parent=None):
        if not isinstance(item, dict):
            rejected.append({'kind':'comment','reason':'invalid_item'})
            return
        cid = _id(item.get('cid'))
        actual_parent = _id(item.get('reply_id'))
        if not cid or _id(item.get('aweme_id')) != video or (parent is not None and actual_parent != parent) or (parent is None and actual_parent not in (None,'0','')):
            rejected.append({'kind':'reply' if parent else 'comment','reason':'video_or_parent_mismatch_or_missing'})
            return
        target = replies if parent else roots
        if cid not in target:
            target[cid] = {'cid':cid,'video_id':video,'parent_cid':parent,'text':_text(item.get('text')),
                           'create_time':item.get('create_time') if isinstance(item.get('create_time'),int) else None,
                           'digg_count':item.get('digg_count') if isinstance(item.get('digg_count'),int) else None}
        if parent is None:
            for reply in item.get('reply_comment') or []:
                add(reply,cid)

    def pages(name, collection, is_reply=False):
        for page in row.get(name) or []:
            if not isinstance(page,dict) or not _owned(page,video):
                rejected.append({'kind':name,'reason':'request_video_mismatch_or_missing'})
                continue
            parent_ids = _refs(page,('comment_id',)) if is_reply else []
            if is_reply and (len(parent_ids) != 1 or parent_ids[0] not in roots):
                rejected.append({'kind':name,'reason':'request_parent_mismatch_or_missing'})
                continue
            if not isinstance(page.get('comments'),list):
                continue
            more = page.get('has_more')
            collection.has_more = bool(int(more)) if more in (0,1,'0','1',False,True) else None
            collection.pages.append({'cursor':page.get('cursor') if re.fullmatch(r'[0-9]+',str(page.get('cursor',''))) else None,
                                     'has_more':collection.has_more,'platform_total':page.get('total') if isinstance(page.get('total'),int) else None})
            if isinstance(page.get('total'),int):
                if is_reply:
                    reply_parent_totals[parent_ids[0]]=page['total']
                    collection.platform_total=sum(reply_parent_totals.values())
                else:collection.platform_total = page['total']
            before_rejections = len(rejected)
            for item in page['comments']:
                add(item,parent_ids[0] if is_reply else None)
            if len(rejected) > before_rejections:
                collection.stop_reason = 'rejected_attribution'
            if page.get('truncated'):
                collection.stop_reason = 'limit_reached'

    pages('comment_pages',root_collection)
    pages('reply_pages',reply_collection,True)
    root_collection.items = list(roots.values())
    reply_collection.items = list(replies.values())
    # Replies are per-parent pagination: one exhausted parent cannot exhaust all.
    if any(p['has_more'] is not False for p in reply_collection.pages):
        reply_collection.has_more = True
    recommendations = {}

    def scenes(value):
        if isinstance(value,list):
            for node in value:
                scenes(node)
        elif isinstance(value,dict):
            if isinstance(value.get('scene'),str):
                scene = _text(value['scene'])
                result = recommendations.setdefault(scene,{'status':'missing','words':[]})
                if 'words' in value:
                    words = value['words']
                    if words is None or isinstance(words,list):
                        for w in words or []:
                            text = _text(w.get('word') if isinstance(w,dict) else w)
                            if text and text not in result['words']:
                                result['words'].append(text)
                        result['status'] = 'available' if result['words'] else 'observed_empty'
            for key in ('suggest_words','value'):
                if key in value:
                    scenes(value[key])

    # These snapshots are associated by the capture producer, not arbitrary scans.
    for snapshot in row.get('nested_suggest_words') or []:
        scenes(snapshot)
    independent = []
    for endpoint in row.get('independent_suggest_words') or []:
        if not isinstance(endpoint,dict) or not _owned(endpoint,video):
            rejected.append({'kind':'independent_suggest_words','reason':'request_video_mismatch_or_missing'})
            continue
        payload = endpoint.get('payload') or {}
        for group in payload.get('data') or []:
            if not isinstance(group,dict):
                continue
            words = list(dict.fromkeys(t for w in group.get('words') or [] if (t := _text(w.get('word') if isinstance(w,dict) else w))))
            independent.append({'type':_text(group.get('type')),'scene':_text(group.get('scene')),
                                'status':('available' if words else 'observed_empty') if 'words' in group else 'missing','words':words,
                                'attribution':'page_level_endpoint'})
    return {'platform':'douyin','video_id':video,'detail':public_detail,
            'comments':_state(root_collection,row.get('comment_gate'),row.get('comment_pagination_status')),
            'replies':_state(reply_collection,row.get('reply_gate'),'partial' if row.get('reply_sampling') and not row.get('reply_gate') and row.get('reply_completeness') not in ('error','blocked_verification','blocked_login') else row.get('reply_completeness')),
            'recommendations':recommendations,'independent_suggest_words':independent,
            'reply_scope':{'meaning':'selected_parents_only','parent_totals':reply_parent_totals},
            'provenance':{'source_sha256':row.get('source_sha256') if re.fullmatch(r'[a-fA-F0-9]{64}',str(row.get('source_sha256',''))) else None,
                          'source':_text(row.get('source')) or 'normal_browser_page',
                          'collected_at':_text(row.get('collected_at'))},'rejections':rejected}
