import unittest

from clipagent.rag import Document, RagIndex, cosine, tokenize


def docs():
    return [
        Document('d1', '水循环', '蒸发使水进入大气，凝结成云，降水回到地面。水循环由太阳能驱动。',
                 'IPCC AR6 WG1 ch8', 'CC BY 4.0'),
        Document('d2', '云的成因', '空气中的水汽遇冷凝结成小水滴，聚集成云。云的形成需要凝结核。',
                 'USGS water cycle', 'public domain'),
        Document('d3', '大气环流', '赤道受热多，极地受热少，温差驱动大气环流。',
                 'NOAA', 'public domain'),
        Document('d4', '光合作用', '植物利用光能把二氧化碳和水合成有机物，释放氧气。',
                 'Campbell Biology', 'citation only'),
    ]


class TokenizeTests(unittest.TestCase):
    def test_cjk_becomes_bigrams(self):
        tokens = tokenize('水循环')
        self.assertIn('水循', tokens)
        self.assertIn('循环', tokens)
        # Unigrams alone retrieve almost everything in Chinese, so they are
        # emitted only for a single-character query.
        self.assertNotIn('水', tokens)

    def test_single_character_query_still_tokenizes(self):
        self.assertEqual(tokenize('水'), ['水'])

    def test_ascii_words_lowercased(self):
        self.assertIn('bm25', tokenize('Hybrid BM25 retrieval'))

    def test_empty_text_gives_no_tokens(self):
        self.assertEqual(tokenize(''), [])


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.index = RagIndex(docs())

    def test_relevant_document_ranks_first(self):
        hits = self.index.search('水汽为什么会凝结成云', k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0].doc_id, 'd2')

    def test_every_hit_carries_source_and_quote(self):
        for hit in self.index.search('水循环', k=3):
            self.assertTrue(hit.source)
            self.assertTrue(hit.quote)
            self.assertIn(hit.license, {'CC BY 4.0', 'public domain', 'citation only'})

    def test_unrelated_query_returns_nothing_rather_than_noise(self):
        self.assertEqual(self.index.search('区块链 智能合约', k=3), [])

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self.index.search('   '), [])
        self.assertEqual(self.index.search(''), [])

    def test_k_is_bounded_and_ordered(self):
        hits = self.index.search('水', k=2)
        self.assertLessEqual(len(hits), 2)
        self.assertEqual(hits, sorted(hits, key=lambda h: (-h.score, h.doc_id)))

    def test_invalid_k_is_rejected(self):
        with self.assertRaises(ValueError):
            self.index.search('水', k=0)

    def test_results_are_deterministic(self):
        a = [h.as_dict() for h in self.index.search('云 凝结', k=4)]
        b = [h.as_dict() for h in self.index.search('云 凝结', k=4)]
        self.assertEqual(a, b)

    def test_reasons_explain_the_match(self):
        hit = self.index.search('凝结', k=1)[0]
        self.assertTrue(hit.reasons)
        self.assertIn('lexical match', hit.reasons)

    def test_method_names_the_vector_limitation(self):
        self.assertIn('not a trained embedding', self.index.method)

    def test_empty_corpus_is_rejected(self):
        with self.assertRaises(ValueError):
            RagIndex([])


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.index = RagIndex(docs())

    def test_sentences_without_a_resolvable_source_are_flagged(self):
        sentences = [
            {'text': '蒸发使水进入大气', 'citation': 'd1'},
            {'text': '云是水做的', 'citation': ''},
            {'text': '某个不存在的来源', 'citation': 'd99'},
        ]
        missing = self.index.assert_cited(sentences)
        self.assertEqual(len(missing), 2)
        self.assertIn('云是水做的', missing)


class CosineTests(unittest.TestCase):
    def test_identical_vectors_are_one(self):
        v = {1: 0.6, 5: 0.8}
        self.assertAlmostEqual(cosine(v, v), 1.0)

    def test_disjoint_vectors_are_zero(self):
        self.assertEqual(cosine({1: 1.0}, {2: 1.0}), 0.0)


if __name__ == '__main__':
    unittest.main()
