"""Deterministic baseline. This module never claims semantic understanding or popularity."""
import hashlib
import json
import re
from datetime import datetime, timezone

WEIGHTS = {'demand': 35, 'evidence': 25, 'explainability': 25, 'freshness': 15}
VERSION = 'research-v1'

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def clean(text):
    return re.sub(r'【模拟[^】]*】|\[demo\]', '', text, flags=re.I).strip()

def normalize(text):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', clean(text).lower())

def category(text):
    if any(word in text for word in ('以为', '不是', '误解')):
        return '疑似认知误区（待核实）'
    if any(word in text for word in ('动画', '解释', '演示', '看不懂')):
        return '解释方式偏好'
    if any(word in text for word in ('骗人', '不信', '争议', '离谱')):
        return '情绪与争议信号'
    return '知识问题'

def rule_clusters(records):
    groups = []
    skipped = 0
    for record in records:
        text = clean(record['text'])
        if len(normalize(text)) < (2 if record['kind'] == 'search' else 4) or text in ('支持支持', '点赞收藏', '学到了谢谢'):
            skipped += 1
            continue
        key = normalize(text)
        # Conservative lexical matching: no inferred synonym or semantic equivalence.
        grams = {key[i:i+2] for i in range(len(key)-1)}
        match = None
        for group in groups:
            prior = group['_grams']
            if key == group['_key'] or (len(key) >= 6 and len(group['_key']) >= 6 and len(grams & prior) / max(1, len(grams | prior)) >= .72):
                match = group
                break
        if match:
            match['evidence_ids'].append(record['id'])
        else:
            groups.append({'title': text[:180], 'question': text[:500], 'category': category(text), 'evidence_ids': [record['id']], '_key': key, '_grams': grams})
    return [{k: v for k, v in group.items() if not k.startswith('_')} for group in groups], skipped

def score_evidence(evidence, weights, reference_time=None):
    unique = len({normalize(e['text']) for e in evidence})
    videos = len({e['video_id'] for e in evidence})
    comments = sum(e['kind'] == 'comment' for e in evidence)
    searches = sum(e['kind'] == 'search' for e in evidence)
    current = reference_time or datetime.now(timezone.utc)
    recent = 0
    for e in evidence:
        collected = datetime.fromisoformat(e['collected_at'])
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=timezone.utc)
        if 0 <= (current - collected).total_seconds() <= 30 * 86400:
            recent += 1
    explain = any(any(word in e['text'] for word in ('为什么', '怎么', '解释', '动画', '原理')) for e in evidence)
    scores = {
        'demand': {'value': min(100, unique * 20), 'reason': f'仅当前样本中 {unique} 种去重表达；不等于受众人数或搜索量'},
        'evidence': {'value': min(100, videos * 25), 'reason': f'来自 {videos} 个视频；同一评论的重复导入不额外计权'},
        'explainability': {'value': 70 if explain else 40, 'reason': '依据疑问/解释/动画词的规则信号；未验证制作成本或叙事质量'},
        'freshness': {'value': round(100 * recent / max(1, len(evidence))), 'reason': '依据采集时间30天窗口，非发布时间、热度或内容生命周期'},
    }
    total = sum(weights.values())
    score = round(sum(scores[k]['value'] * weights[k] for k in WEIGHTS) / total, 2)
    coverage = {'videos': videos, 'comments': comments, 'unique_comments': len({normalize(e['text']) for e in evidence if e['kind'] == 'comment'}), 'searches': searches, 'unique_expressions': unique}
    return score, scores, coverage, unique

def grounded_topics(groups, records, weights, engine, reference_time=None):
    lookup = {record['id']: record for record in records}
    result = []
    for group in groups:
        ids = group['evidence_ids']
        if not ids or any(identifier not in lookup for identifier in ids):
            raise ValueError('分析结果包含不存在的来源ID')
        evidence = [lookup[key] for key in dict.fromkeys(ids)]
        score, scores, coverage, support = score_evidence(evidence, weights, reference_time)
        result.append({**{k: group[k] for k in ('title', 'question', 'category')}, 'evidence': evidence, 'score': score, 'scores': scores, 'coverage': coverage, 'support_count': support,
            'uncertainty': ('规则仅进行文本去重/字面相似归组，不能识别所有同义问题。' if engine == 'rules' else '模型语义归组可能误分，需人工核对原文。') + '样本非随机且规模有限，不能推断平台整体需求；支持数是去重表达数，不是独立观众数。',
            'gap': '这是待研究的内容缺口假设；仅有导入资料，尚未核查完整竞品内容和外部科学来源。'})
    return result
