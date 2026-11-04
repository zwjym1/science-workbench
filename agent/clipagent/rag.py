"""Retrieval over the corpus the agent writes from.

Three stages, all inspectable: BM25 for lexical recall, hashed feature vectors
for a second, independent ranking, then a rerank that combines them plus an
exact-phrase bonus. Every hit carries its source and the sentence it came from,
because a citation you cannot trace is a citation you cannot defend.

No third-party dependency and no network: the vector stage is feature hashing,
not a trained embedding. That is a real limitation and it is named in the
results rather than hidden, so swapping in a real embedder later is a change of
one function, not a rewrite.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field, asdict
from typing import Iterable, Sequence

VECTOR_DIM = 512
K1, B = 1.5, 0.75
# Feature hashing collides; below this cosine the "match" is noise, not signal.
MIN_COSINE = 0.15

_CJK = re.compile(r'[\u4e00-\u9fff]')
_WORD = re.compile(r'[a-z0-9_]+')


def tokenize(text: str) -> list[str]:
    """CJK bigrams plus lowercase ASCII words.

    A unigram index over Chinese retrieves almost everything; bigrams keep
    precision without pulling in a segmenter.
    """
    text = text.lower()
    tokens = _WORD.findall(text)
    chars = [c for c in text if _CJK.match(c)]
    if len(chars) == 1:
        tokens.append(chars[0])       # a one-character query has no bigram
    else:
        tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
    return tokens


def _hash_vector(tokens: Sequence[str]) -> dict[int, float]:
    vector: dict[int, float] = {}
    for token in tokens:
        digest = hashlib.blake2b(token.encode('utf-8'), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], 'big') % VECTOR_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] = vector.get(bucket, 0.0) + sign
    norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
    return {k: v / norm for k, v in vector.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


@dataclass
class Document:
    id: str
    title: str
    text: str
    source: str
    license: str = 'unknown'

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Hit:
    doc_id: str
    title: str
    source: str
    license: str
    score: float
    bm25: float
    cosine: float
    quote: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


class RagIndex:
    def __init__(self, documents: Iterable[Document]):
        self.docs = list(documents)
        if not self.docs:
            raise ValueError('an index needs at least one document')
        self._tokens = [tokenize(f'{d.title} {d.text}') for d in self.docs]
        self._tf = [self._count(t) for t in self._tokens]
        self._len = [len(t) or 1 for t in self._tokens]
        self._avg = sum(self._len) / len(self._len)
        self._df: dict[str, int] = {}
        for tokens in self._tokens:
            for term in set(tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._vectors = [_hash_vector(t) for t in self._tokens]
        self.method = ('bm25 (k1=%.1f, b=%.2f) + hashed feature vectors (dim=%d) '
                       '+ phrase-bonus rerank; vectors are lexical hashing, '
                       'not a trained embedding' % (K1, B, VECTOR_DIM))

    @staticmethod
    def _count(tokens: Sequence[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for token in tokens:
            out[token] = out.get(token, 0) + 1
        return out

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        n = len(self.docs)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def _bm25(self, index: int, query_terms: list[str]) -> float:
        tf, length = self._tf[index], self._len[index]
        score = 0.0
        for term in query_terms:
            freq = tf.get(term)
            if not freq:
                continue
            denom = freq + K1 * (1 - B + B * length / self._avg)
            score += self._idf(term) * freq * (K1 + 1) / denom
        return score

    def _quote(self, doc: Document, query: str) -> str:
        best, best_score = '', -1
        for sentence in re.split(r'(?<=[。！？.!?])', doc.text):
            sentence = sentence.strip()
            if not sentence:
                continue
            terms = set(tokenize(query))
            score = sum(1 for t in tokenize(sentence) if t in terms)
            if score > best_score:
                best, best_score = sentence, score
        return best[:160]

    def search(self, query: str, k: int = 5) -> list[Hit]:
        query = (query or '').strip()
        if not query:
            return []
        if k < 1:
            raise ValueError('k must be positive')
        terms = tokenize(query)
        if not terms:
            return []
        qvec = _hash_vector(terms)
        phrase = query.lower()

        raw = []
        for i, doc in enumerate(self.docs):
            bm25 = self._bm25(i, terms)
            cos = cosine(qvec, self._vectors[i])
            bonus = 0.2 if phrase and phrase in f'{doc.title} {doc.text}'.lower() else 0.0
            raw.append((bm25, cos, bonus, i))

        top_bm25 = max((r[0] for r in raw), default=0.0) or 1.0
        hits = []
        for bm25, cos, bonus, i in raw:
            if bm25 <= 0 and cos < MIN_COSINE:
                continue
            score = 0.6 * (bm25 / top_bm25) + 0.4 * max(cos, 0.0) + bonus
            doc = self.docs[i]
            reasons = []
            if bm25 > 0:
                reasons.append('lexical match')
            if cos > 0:
                reasons.append('vector match')
            if bonus:
                reasons.append('exact phrase in text')
            hits.append(Hit(doc_id=doc.id, title=doc.title, source=doc.source,
                            license=doc.license, score=round(score, 4),
                            bm25=round(bm25, 4), cosine=round(cos, 4),
                            quote=self._quote(doc, query), reasons=reasons))
        hits.sort(key=lambda h: (-h.score, h.doc_id))
        return hits[:k]

    def assert_cited(self, answer_sentences: Sequence[dict]) -> list[str]:
        """Return the sentences that claim a fact without a resolvable source."""
        known = {d.id for d in self.docs}
        missing = []
        for item in answer_sentences:
            citation = item.get('citation')
            if not citation or citation not in known:
                missing.append(item.get('text', ''))
        return missing
