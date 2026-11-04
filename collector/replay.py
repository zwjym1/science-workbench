"""Offline historical normalization. Never imports a network client."""
import argparse
import os
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from dycollector.normalize import normalize_capture


def default_source():
    """Evidence lives outside the repo; point DYCOLLECTOR_EVIDENCE at a batch summary."""
    override = os.environ.get('DYCOLLECTOR_EVIDENCE')
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / 'research/douyin-validation/evidence/batch20/summary.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=default_source())
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).resolve().parent / 'data/replay-report.json')
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if source == output:
        parser.error('output must differ from historical source')
    raw = source.read_bytes()
    capture = json.loads(raw)
    source_time = capture.get('ended_at')
    rows = []
    for row in capture['rows']:
        normalized = normalize_capture(row)
        normalized['replay'] = True
        normalized['source_collected_at'] = source_time
        # Batch summary only has a batch end timestamp, not per-row collection time.
        normalized['provenance']['source_batch_ended_at'] = source_time
        rows.append(normalized)
    totals = {'videos':len(rows),
              'details_available':sum(r['detail']['status'] == 'available' for r in rows),
              'unique_top_level_comments':sum(r['comments']['unique_count'] for r in rows),
              'unique_replies':sum(r['replies']['unique_count'] for r in rows),
              'rejections':sum(len(r['rejections']) for r in rows)}
    report = {'replay':True,'generated_at':datetime.now(timezone.utc).isoformat(),
              'source_collected_at':source_time,'source_time_scope':'batch_ended_at',
              'source':source.name,'source_sha256':hashlib.sha256(raw).hexdigest(),
              'limitations':['Historical offline replay; no live requests performed.',
                             'Batch end timestamp is not a per-row collection timestamp.',
                             'Independent suggestions remain page-level; no inferred UI placement.',
                             'Comment totals are platform totals, not a completeness guarantee.'],
              'totals':totals,'rows':rows}
    output.parent.mkdir(parents=True,exist_ok=True)
    # Keep each existing replay artifact intact as well as historical evidence.
    with output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    assert source.read_bytes() == raw, 'historical source changed during replay'
    print(json.dumps({'replay':True,'output':str(output),'totals':totals},ensure_ascii=True))


if __name__ == '__main__':
    main()
