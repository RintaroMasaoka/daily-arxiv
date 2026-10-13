"""Build time-scale-aware lexical evidence for research-line analysis.

Run from the repository root. Lexical measurements support content review;
research states and reading priorities require historical and semantic evidence.
"""
from __future__ import annotations
import argparse
import calendar
import collections
from datetime import date
import json
from pathlib import Path
import re


def shift_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def parse_day(value: str) -> date:
    value = value[:10]
    if '-' not in value:
        value = f'{value[:4]}-{value[4:6]}-{value[6:8]}'
    return date.fromisoformat(value)


def covered(start: date, end: date, intervals: list[tuple[date, date]]) -> bool:
    cursor = start
    for lo, hi in sorted(intervals):
        if hi <= cursor:
            continue
        if lo > cursor:
            return False
        cursor = max(cursor, hi)
        if cursor >= end:
            return True
    return False


def normalize(text: str) -> str:
    text = text.lower().replace('–', '-').replace('—', '-').replace('−', '-')
    text = re.sub(r'\\(?:mathrm|text|textrm|mathbb|ce)', '', text)
    return re.sub(r'[$_{}]', '', text)


def analyze(corpus: dict, config: dict, lexicon: dict) -> dict:
    end = parse_day(corpus['target_until_exclusive'])
    recent_start = shift_months(end, -config['recent_months'])
    context_start = shift_months(end, -12 * config['history_years'])
    papers = corpus['papers']
    ids = [p['arxiv_id'] for p in papers]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate arXiv IDs in input')
    if any(not p.get('published') for p in papers):
        raise ValueError('First-submission timestamps are required')
    if any(corpus['category'] not in p['categories'] for p in papers):
        raise ValueError('Input contains papers outside the requested category')
    # Include only slices with verified query totals in the completeness mask.
    intervals = [
        (parse_day(q['from']), parse_day(q['until_exclusive']))
        for q in corpus.get('queries', [])
        if q.get('unique_fetched') == q.get('total_results')
        and isinstance(q.get('total_results'), int)
        and q.get('query', '').startswith(f"cat:{corpus['category']} ")
    ]
    dated = [(p, parse_day(p['published'])) for p in papers]

    def measure(start: date, stop: date, regex: re.Pattern | None = None,
                primary_only: bool = False, abstract: bool = False) -> dict:
        subset = [p for p, d in dated if start <= d < stop
                  and (not primary_only or p.get('primary_category') == corpus['category'])]
        complete = covered(start, stop, intervals)
        matched = subset if regex is None else [
            p for p in subset
            if regex.search(normalize(p['title'] + (' ' + p['abstract'] if abstract else '')))
        ]
        return {
            'from': start.isoformat(), 'until_exclusive': stop.isoformat(),
            'coverage_complete': complete,
            'observed_papers': len(subset), 'observed_matches': len(matched),
            'papers': len(subset) if complete else None,
            'matches': len(matched) if complete else None,
            'pct': 100 * len(matched) / len(subset) if complete and subset else None,
        }

    windows = {
        'recent_3_months': (recent_start, end),
        'current_12_months': (shift_months(end, -12), end),
        'previous_12_months': (shift_months(end, -24), shift_months(end, -12)),
        'previous_24_months': (shift_months(end, -36), shift_months(end, -12)),
        'same_quarter_previous_year': (shift_months(recent_start, -12), shift_months(end, -12)),
    }
    quarters = [(shift_months(end, i), shift_months(end, i + 3))
                for i in range(-12 * config['history_years'], 0, 3)]
    years = [(shift_months(end, i), shift_months(end, i + 12))
             for i in range(-12 * config['history_years'], 0, 12)]
    full_context = covered(context_start, end, intervals)
    rows = []
    for axis, patterns in lexicon.items():
        for label, pattern in patterns.items():
            regex = re.compile(pattern)
            modes = {}
            for mode, kwargs in [('title', {}), ('title_or_abstract', {'abstract': True}),
                                 ('primary_title', {'primary_only': True})]:
                modes[mode] = {
                    'windows': {name: measure(lo, hi, regex, **kwargs)
                                for name, (lo, hi) in windows.items()},
                    'quarters': [measure(lo, hi, regex, **kwargs) for lo, hi in quarters],
                    'years': [measure(lo, hi, regex, **kwargs) for lo, hi in years],
                }
            current = [p['arxiv_id'] for p, day in dated
                       if recent_start <= day < end and regex.search(normalize(p['title']))]
            rows.append({'axis': axis, 'label': label, 'regex': pattern,
                         'measurements': modes, 'recent_title_ids': current,
                         'research_state': 'requires_historical_and_content_review'})

    # Current phrases broaden discovery even when their frequency is stable.
    stopwords = set('the a an of in on for and with by from to at as via into its their '
                    'this that using based study effects effect model models system '
                    'systems quantum electron electrons electronic spin spins'.split())
    terms = collections.Counter()
    for p, day in dated:
        if recent_start <= day < end:
            words = re.findall(r'[a-z][a-z-]{2,}', normalize(p['title']))
            candidates = {w for w in words if w not in stopwords}
            candidates |= {a + ' ' + b for a, b in zip(words, words[1:])
                           if a not in stopwords and b not in stopwords}
            terms.update(candidates)
    return {
        'schema_version': 2,
        'scope': corpus['category'],
        'recent_window': [recent_start.isoformat(), end.isoformat()],
        'context_window': [context_start.isoformat(), end.isoformat()],
        'historical_context_complete': full_context,
        'analysis_status': 'historical_and_content_review_required' if full_context
                           else 'historical_data_required',
        'corpus_windows': {name: measure(lo, hi) for name, (lo, hi) in windows.items()},
        'topics': rows,
        'recent_title_terms': [{'term': t, 'count': n} for t, n in terms.most_common(80)],
        'interpretation': 'Lexical evidence for research-line review. Missing periods are '
                          'null, not zero. Measurements do not determine research states '
                          'or reading priorities. Candidate discovery also uses historical '
                          'reviews and recent paper introductions/references.',
        'abstract_version_policy': 'Retrieved abstracts may contain later revisions. '
                                   'Check version history when establishing milestones.',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=Path('research/trends/corpus.json'))
    parser.add_argument('--framework', type=Path, default=Path('research/trends/framework.json'))
    parser.add_argument('--lexicon', type=Path, default=Path('research/trends/topic_lexicon.json'))
    parser.add_argument('--output', type=Path, default=Path('research/trends/screen.json'))
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text())
    result = analyze(read(args.corpus), read(args.framework), read(args.lexicon))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in
                      ['analysis_status', 'recent_window', 'context_window',
                       'historical_context_complete']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
