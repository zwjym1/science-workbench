"""Bounded, guest-only reads from Douyin's public search host.

No retries, signature generation, authentication import or alternate hosts.
The caller owns the guest context and the source-wide pause policy.
"""
import asyncio
import json
import time
from datetime import datetime, timezone

from .browser import parse_video_ref


BASE = 'https://so.douyin.com/aweme/v1/web/'
PARAMS = {'aid': '581610', 'channel': 'channel_pc_web',
          'platform': 'PC', 'device_platform': 'webapp'}
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
      'Mobile/15E148 Safari/604.1')


class _Stop(Exception):
    pass


class PublicAPI:
    def __init__(self, store, context):
        self.store, self.context = store, context

    async def _get(self, row, endpoint, params):
        refs = {k: [str(v)] for k, v in params.items()}
        record = {'path': '/aweme/v1/web/' + endpoint,
                  'references': refs, 'source': 'so.douyin.com'}
        row['responses'].append(record)
        response = None
        try:
            response = await self.context.request.get(
                BASE + endpoint, params={**PARAMS, **params},
                headers={'User-Agent': UA, 'Referer': 'https://so.douyin.com/'},
                timeout=20000, max_redirects=0, max_retries=0)
            record['status'] = response.status
            if response.status in (401, 403, 429):
                row['restriction'] = f'HTTP {response.status}'
            body = await response.body()
            record.update(self.store.save_raw(body))
            if response.status in (401, 403, 429):
                row['restriction'] = f'HTTP {response.status}'
                raise _Stop()
            if not 200 <= response.status < 300:
                record['error_type'] = 'HTTPError'
                raise _Stop()
            try:
                data = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                text = body[:16000].decode('utf-8', 'replace').lower()
                if any(word in text for word in ('登录', 'login', '验证码', 'verify', '安全验证', '访问过于频繁')):
                    row['restriction'] = 'non-JSON access verification'
                else:
                    record['error_type'] = 'InvalidJSON'
                raise _Stop()
            if not isinstance(data, dict):
                record['error_type'] = 'InvalidPayload'
                raise _Stop()
            code = data.get('status_code')
            record['platform_status_code'] = code
            # Treat all explicit nonzero codes conservatively; the caller pauses
            # rather than selecting another source or retrying the identity.
            if code not in (None, 0, '0'):
                row['restriction'] = 'platform nonzero status_code'
                raise _Stop()
            return data
        except _Stop:
            raise
        except Exception as exc:
            record['error_type'] = type(exc).__name__
            raise _Stop() from None
        finally:
            if response is not None:
                try:
                    await response.dispose()
                except Exception:
                    # Cleanup must never erase a previously observed restriction.
                    pass

    async def _pages(self, row, video, *, parent=None, max_pages, limit):
        endpoint = 'comment/list/reply/' if parent else 'comment/list/'
        params = {'item_id': video, 'comment_id': parent} if parent else {'aweme_id': video}
        dest = row['reply_pages'] if parent else row['comment_pages']
        cursor, seen_cursors, seen, selected = 0, set(), set(), []
        for _ in range(max_pages):
            if cursor in seen_cursors:
                row['reply_sampling' if parent else 'comment_pagination_stop'] = 'cursor_stuck'
                break
            seen_cursors.add(cursor)
            request_params = {**params, 'cursor': cursor, 'count': min(20, limit - len(selected))}
            data = await self._get(row, endpoint, request_params)
            values = data.get('comments')
            if not isinstance(values, list):
                row['reply_completeness' if parent else 'comment_pagination_status'] = 'error'
                break
            page_items = []
            # Keep conflicting items for normalizer rejection; never let the
            # target_identified flag stand in for per-item ownership validation.
            for item in values:
                cid = str(item.get('cid')) if isinstance(item, dict) and item.get('cid') is not None else None
                if cid and cid in seen:
                    continue
                if cid:
                    seen.add(cid)
                page_items.append(item)
            remaining = limit - len(selected)
            truncated = len(page_items) > remaining
            page_items = page_items[:remaining]
            page = {'target_identified': True,
                    'references': {k: [str(v)] for k, v in request_params.items()},
                    'comments': page_items, 'total': data.get('total'),
                    'cursor': data.get('cursor'), 'has_more': data.get('has_more'),
                    'truncated': truncated}
            dest.append(page)
            selected.extend(page_items)
            if truncated:
                row['reply_sampling' if parent else 'comment_limit_reached'] = True
                break
            if data.get('has_more') in (0, False, '0'):
                break
            if len(selected) >= limit:
                row['reply_sampling' if parent else 'comment_limit_reached'] = True
                break
            if not values:
                row['reply_sampling' if parent else 'comment_pagination_stop'] = 'empty_page'
                break
            next_cursor = data.get('cursor')
            if not isinstance(next_cursor, (int, str)) or not str(next_cursor).isdigit():
                row['reply_sampling' if parent else 'comment_pagination_stop'] = 'cursor_invalid'
                break
            cursor = int(next_cursor)
            await asyncio.sleep(0.8)
        return selected

    async def collect(self, video_id, *, max_pages=3, max_comments=50):
        video = parse_video_ref(video_id)
        if type(max_pages) is not int or not 1 <= max_pages <= 20:
            raise ValueError('max_pages must be 1..20')
        if type(max_comments) is not int or not 1 <= max_comments <= 500:
            raise ValueError('max_comments must be 1..500')
        row = {'video_id': video, 'source': 'so.douyin.com',
               'collected_at': datetime.now(timezone.utc).isoformat(),
               'detail': None, 'nested_suggest_words': [], 'comment_pages': [],
               'reply_pages': [], 'responses': [], 'independent_suggest_words': [],
               'actions': [], 'manual_intervention': False}
        started = time.perf_counter()
        stage = 'detail'
        try:
            data = await self._get(row, 'aweme/detail/', {'aweme_id': video})
            detail = data.get('aweme_detail')
            if not isinstance(detail, dict) or str(detail.get('aweme_id')) != video:
                row['detail_status'] = 'missing' if not detail else 'rejected_attribution'
                row['comment_pagination_status'] = 'not_requested'
                row['reply_completeness'] = 'not_requested'
                return row
            row['detail'] = detail
            if 'suggest_words' in detail:
                row['nested_suggest_words'].append({'json_path': '$.aweme_detail.suggest_words', 'value': detail['suggest_words']})
            stage = 'comments'
            items = await self._pages(row, video, max_pages=max_pages, limit=max_comments)
            parents = [c for c in items if isinstance(c, dict)
                       and str(c.get('aweme_id')) == video
                       and str(c.get('reply_id', '0')) in ('0', '')
                       and c.get('cid') is not None
                       and isinstance(c.get('reply_comment_total'), int)
                       and c['reply_comment_total'] > 0]
            parents.sort(key=lambda c: c.get('digg_count') if isinstance(c.get('digg_count'), int) else 0, reverse=True)
            stage = 'replies'
            for parent in parents[:3]:
                await asyncio.sleep(0.6)
                await self._pages(row, video, parent=str(parent['cid']), max_pages=1, limit=3)
            # One sampled parent's last page cannot prove video-wide completeness.
            if parents or row.get('comment_limit_reached') or any(p['has_more'] not in (0, False, '0') for p in row['comment_pages']):
                row['reply_sampling'] = True
                row['reply_completeness'] = 'partial'
            elif row['comment_pages'] and all(isinstance(c,dict) and c.get('reply_comment_total')==0 for c in items):
                row['reply_completeness']='observed_empty'
        except _Stop:
            hint = 'blocked_verification' if row.get('restriction') else 'error'
            if stage == 'detail':
                row['detail_status'] = hint
            row['reply_completeness' if stage == 'replies' else 'comment_pagination_status'] = hint
        finally:
            row['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        return row
