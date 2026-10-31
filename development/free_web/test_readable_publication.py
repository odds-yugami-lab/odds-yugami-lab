"""Regression checks for public-readable prediction pages (offline, no bets)."""
import unittest
from two_researcher_runner import readable_prediction, paths


class ReadablePublicationTest(unittest.TestCase):
    def test_both_researchers_full_ticket_listing(self):
        pair = {
            'race_name': '架空の検証レース',
            'race_start_at': '2026-11-01T15:40:00+09:00',
            'prediction_finalized_at': '2026-11-01T15:15:00+09:00',
            'researchers': {
                'ichiro': {'researcher_name': '一郎研究員',
                           'total_stake_yen': 100, 'unspent_yen': 9900,
                           'tickets': [{'bet_type': 'umaren', 'kumiban': '0102',
                                        'stake': 100, 'decimal_odds': 110.0}]},
                'matsui': {'researcher_name': 'マツイ研究員',
                           'total_stake_yen': 100, 'unspent_yen': 9900,
                           'tickets': [{'bet_type': 'sanrenpuku', 'kumiban': '010203',
                                        'stake': 100, 'decimal_odds': 130.0}]},
            }
        }
        page = readable_prediction(pair, 'https://example.invalid/immutable.json')
        self.assertIn('| 馬連 | 1-2 | 100円 | 110.0倍 |', page)
        self.assertIn('| 3連複 | 1-2-3 | 100円 | 130.0倍 |', page)
        self.assertIn('一郎研究員', page)
        self.assertIn('マツイ研究員', page)
        self.assertIn('https://example.invalid/immutable.json', page)
        self.assertEqual(page.count('| 馬連 |'), 1)
        self.assertEqual(page.count('| 3連複 |'), 1)

    def test_live_path_has_readable_and_test_path_isolated(self):
        self.assertEqual(paths('2026110108040111')['readable'],
                         'publications/researchers/2026110108040111_readable.md')
        self.assertNotIn('readable', paths('2026110108040111', True, 'regression'))


if __name__ == '__main__':
    unittest.main()
