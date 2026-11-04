import csv
import io
from pydantic import Field
from .schemas import StrictModel, StandardData

COLUMNS = {'platform', 'external_id', 'title', 'source_url', 'collected_at', 'published_at', 'content', 'comment_id', 'comment_text', 'comment_likes', 'related_searches', 'tags', 'views', 'likes'}
REQUIRED = {'platform', 'external_id', 'title', 'source_url', 'collected_at'}

class CsvImportRequest(StrictModel):
    is_demo: bool
    csv_text: str = Field(min_length=1, max_length=5 * 1024 * 1024)
    mapping: dict[str, str] = Field(default_factory=dict, max_length=30)

class CsvAdapter:
    def normalize(self, payload):
        mapping = payload.get('mapping', {})
        if set(mapping) - COLUMNS:
            raise ValueError('CSV映射包含不支持的标准字段')
        reader = csv.DictReader(io.StringIO(payload['csv_text'].lstrip('\ufeff')))
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError('CSV列名不能重复')
        if any(mapping.get(key, key) not in headers for key in REQUIRED):
            raise ValueError('CSV缺少必填列：platform/external_id/title/source_url/collected_at')
        if any(value not in headers for value in mapping.values()):
            raise ValueError('映射指向的CSV列不存在')
        videos = {}
        for row_number, row in enumerate(reader, 2):
            if row_number > 10001 or None in row or any(value is None for value in row.values()):
                raise ValueError('CSV行数超过10000，或某行列数与表头不一致')
            def get(key):
                return row.get(mapping.get(key, key), '').strip()
            key = (get('platform'), get('external_id'))
            base = {name: get(name) for name in REQUIRED}
            for name in ('published_at', 'content'):
                if get(name):
                    base[name] = get(name)
            for name in ('related_searches', 'tags'):
                if get(name):
                    base[name] = [part.strip() for part in get(name).split('|') if part.strip()]
            base['metrics'] = {name: int(get(name)) if get(name) else None for name in ('views', 'likes') if mapping.get(name, name) in headers}
            if key in videos:
                old = {name: value for name, value in videos[key].items() if name != 'comments'}
                if old != base:
                    raise ValueError(f'CSV第{row_number}行与相同视频的元数据不一致')
            else:
                videos[key] = {**base, 'comments': []}
            if get('comment_text'):
                if not get('comment_id'):
                    raise ValueError(f'CSV第{row_number}行评论缺少稳定comment_id')
                comment = {'external_id': get('comment_id'), 'text': get('comment_text')}
                if mapping.get('comment_likes', 'comment_likes') in headers:
                    comment['likes'] = int(get('comment_likes')) if get('comment_likes') else None
                videos[key]['comments'].append(comment)
        return StandardData.model_validate({'videos': list(videos.values())})
