import copy
import unittest
import json
from pathlib import Path
from copy_product import normalize, price_of, source_url
from target_plan import make_plan


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://item.taobao.com/item.htm?id=123&skuId=99'
        self.raw = {'item': {'itemId': '123', 'title': '测试', 'images': ['//img.alicdn.com/a.jpg']},
                    'properties': [{'id': 'a', 'name': '规格', 'values': [{'id': 'b', 'name': '1斤'}, {'id': 'c', 'name': '3斤'}]}],
                    'skus': [{'id': '99', 'path': 'a:b'}, {'id': '100', 'path': 'a:c'}],
                    'offers': {'99': {'priceText': '6.8', 'priceMoney': '680', 'displayedQuantity': 200, 'moreQuantity': True},
                               '100': {'priceText': '16.9', 'priceMoney': '1690'}}}

    def test_preserves_sku_prices_and_does_not_copy_stock(self):
        p = normalize(self.raw, self.url, [])
        self.assertEqual([s['price'] for s in p['skus']], ['6.80', '16.90'])
        self.assertTrue(p['skus'][0]['source_quantity_is_capped'])
        self.assertIsNone(p['skus'][0]['target_stock'])

    def test_rejects_other_product(self):
        with self.assertRaises(ValueError):
            normalize(self.raw, 'https://item.taobao.com/item.htm?id=456', [])

    def test_missing_sku_price_is_not_minimum_price(self):
        del self.raw['offers']['100']
        self.raw['offers']['0'] = {'priceText': '1'}
        with self.assertRaises(ValueError):
            normalize(self.raw, self.url, [])

    def test_duplicate_combinations_rejected(self):
        self.raw['skus'][1]['path'] = 'a:b'
        with self.assertRaises(ValueError):
            normalize(self.raw, self.url, [])

    def test_unknown_property_rejected(self):
        self.raw['skus'][1]['path'] = 'a:z'
        with self.assertRaises(ValueError):
            normalize(self.raw, self.url, [])

    def test_missing_dimension_rejected(self):
        self.raw['skus'][1]['path'] = ''
        with self.assertRaises(ValueError):
            normalize(self.raw, self.url, [])

    def test_range_and_currency_mismatch_rejected(self):
        for value in [{'priceText': '6-8'}, {'priceText': '6.8', 'priceMoney': '6800'}]:
            with self.assertRaises(ValueError):
                price_of(value)

    def test_no_cartesian_product_generated(self):
        self.raw['properties'].append({'id': 'd', 'name': '包装', 'values': [{'id': 'e', 'name': '盒'}, {'id': 'f', 'name': '袋'}]})
        self.raw['skus'][0]['path'] += ';d:e'
        self.raw['skus'][1]['path'] += ';d:f'
        self.assertEqual(len(normalize(self.raw, self.url, [])['skus']), 2)

    def test_host_validation(self):
        with self.assertRaises(ValueError):
            source_url('https://item.taobao.com.evil.test/item.htm?id=123')

    def test_target_brand_and_stock_are_independent(self):
        source = normalize(self.raw, self.url, [])
        plan = make_plan(source, {'brand': '无品牌', 'stock_per_sku': 88})
        self.assertEqual(plan['brand'], '无品牌')
        self.assertEqual(plan['skus'][0]['target_stock'], 88)
        self.assertIsNone(source['skus'][0]['target_stock'])
        self.assertIn('shipping_template', plan['needs_configuration'])

    def test_renaming_must_not_merge_distinct_prices(self):
        source = normalize(self.raw, self.url, [])
        with self.assertRaises(ValueError):
            make_plan(source, {'sku_value_names': {'a:b': '同名', 'a:c': '同名'}})

    def test_unknown_price_override_is_rejected(self):
        source = normalize(self.raw, self.url, [])
        with self.assertRaises(ValueError):
            make_plan(source, {'price_overrides': {'not-a-sku': '9.90'}})

    def test_confirmed_sample_plain_express_plan(self):
        root = Path(__file__).resolve().parent.parent
        product_path = root / 'output/python-copy/745182817868/product.json'
        if not product_path.exists():
            self.skipTest('本机商品样本未提供')
        product = json.loads(product_path.read_text(encoding='utf-8'))
        settings = json.loads((root / 'python_copy/target-settings.json').read_text(encoding='utf-8'))
        plan = make_plan(product, settings)
        self.assertTrue(plan['target_configuration_complete'])
        self.assertEqual(len(plan['skus']), 8)
        self.assertEqual(sum(s['target_stock'] for s in plan['skus']), 704)
        self.assertFalse(any('顺丰' in v['value'] or '京东' in v['value'] for s in plan['skus'] for v in s['values']))
        self.assertEqual(plan['shipping']['shipping_origin'], {'province': '广西', 'city': '梧州'})


if __name__ == '__main__':
    unittest.main()
