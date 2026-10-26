"""Build an editable destination plan without claiming it was filled or submitted."""
import argparse
import copy
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from copy_product import price_of


def make_plan(source, settings):
    plan = copy.deepcopy(source)
    plan['status'] = 'target_plan_not_filled'
    plan['brand'] = settings.get('brand')
    plan['title'] = settings.get('title') or source['title']
    plan['category'] = settings.get('category')
    plan['shipping'] = {k: settings.get(k) for k in ['shipping_origin', 'shipping_template', 'carrier']}
    missing = [k for k in ['brand', 'category', 'shipping_origin', 'shipping_template', 'carrier'] if not settings.get(k)]
    stock = settings.get('stock_per_sku')
    if type(stock) is not int or stock < 0:
        missing.append('stock_per_sku')
        stock = None
    if sum(1 if ord(c) < 128 else 2 for c in plan['title']) > 60:
        missing.append('title_exceeds_60_characters')
    source_ids = {s['source_sku_id'] for s in source['skus']}
    if set(settings.get('excluded_source_skus', [])) - source_ids:
        raise ValueError('排除清单包含不存在的 SKU')
    if set(settings.get('price_overrides', {})) - source_ids:
        raise ValueError('改价清单包含不存在的 SKU')
    plan['skus'] = [s for s in plan['skus'] if s['source_sku_id'] not in settings.get('excluded_source_skus', [])]
    combinations = set()
    for sku in plan['skus']:
        sku['target_stock'] = stock
        rule = settings.get('price_rule', {})
        multiplier = Decimal(str(rule.get('multiplier', '1')))
        addition = Decimal(str(rule.get('addition', '0')))
        if not multiplier.is_finite() or multiplier <= 0 or not addition.is_finite():
            raise ValueError('价格倍率必须为正数，加价必须为有限数字')
        sku['price'] = price_of({'priceText': format((Decimal(sku['price']) * multiplier + addition).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f')})
        if sku['source_sku_id'] in settings.get('price_overrides', {}):
            sku['price'] = price_of({'priceText': str(settings['price_overrides'][sku['source_sku_id']])})
            sku['price_label'] = '用户设置'
        for value in sku['values']:
            key = value['property_id'] + ':' + value['value_id']
            original = value['value']
            alias = settings.get('sku_value_names', {}).get(key)
            if alias:
                value['value'] = alias
            elif any(word in original for word in ['顺丰', '京东', '普通快递']):
                missing.append('sku_value_names.' + key)
        combination = tuple(sorted((v['property_id'], v['value']) for v in sku['values']))
        if combination in combinations:
            raise ValueError('改名后出现同名规格组合；请明确保留哪一项及其价格，不能静默合并')
        combinations.add(combination)
    if not plan['skus']:
        raise ValueError('没有可复制的 SKU')
    # The old source property list is evidence only; rebuild target labels from rows.
    plan['source_properties'] = plan.pop('properties')
    props = {}
    for sku in plan['skus']:
        for value in sku['values']:
            prop = props.setdefault(value['property_id'], {'id': value['property_id'], 'name': value['property'], 'values': {}})
            prop['values'][value['value_id']] = {'id': value['value_id'], 'name': value['value'], 'image': value['image']}
    plan['properties'] = [{**p, 'values': list(p['values'].values())} for p in props.values()]
    plan['needs_configuration'] = sorted(set(missing))
    plan['target_configuration_complete'] = not missing
    return plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('product', type=Path)
    parser.add_argument('--settings', type=Path, default=Path(__file__).with_name('target-settings.json'))
    args = parser.parse_args()
    plan = make_plan(json.loads(args.product.read_text(encoding='utf-8')),
                     json.loads(args.settings.read_text(encoding='utf-8')))
    output = args.product.with_name('target-plan.json')
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print('目标品牌：' + str(plan['brand']))
    print('待配置：' + ', '.join(plan['needs_configuration']))
    print('已保存（未填入、未发布）：' + str(output))


if __name__ == '__main__':
    main()
