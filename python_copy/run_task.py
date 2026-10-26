"""Config-driven collector/editor/publisher used by the desktop launcher."""
import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from playwright.sync_api import sync_playwright
from copy_product import ROOT, source_url, collect
from target_plan import make_plan
from draft_product import fill_review_draft
from publishing import publish_once


def validate_task(task):
    source_url(task['url'])
    s = task['settings']
    for key in ['shop_name','brand','category','shipping_template','dispatch_time']:
        if not isinstance(s.get(key), str) or not s[key].strip():
            raise ValueError('缺少配置：' + key)
    if s['dispatch_time'] not in ['24小时内发货','48小时内发货','大于48小时发货']:
        raise ValueError('请选择有效发货时限')
    if type(s.get('stock_per_sku')) is not int or s['stock_per_sku'] < 0:
        raise ValueError('库存必须为非负整数')
    if not all(s.get('shipping_origin', {}).get(k) for k in ['province','city']):
        raise ValueError('缺少发货省市')
    if not isinstance(s.get('attributes', {}), dict):
        raise ValueError('类目属性必须是名称与值组成的对象')
    if task.get('mode') not in ['draft','publish']:
        raise ValueError('无效运行模式')
    rule = s.get('price_rule', {})
    multiplier, addition = Decimal(str(rule.get('multiplier', 1))), Decimal(str(rule.get('addition', 0)))
    if not multiplier.is_finite() or multiplier <= 0 or not addition.is_finite():
        raise ValueError('价格倍率必须大于零，加价必须为有限数字')
    indexes = s.get('main_image_indexes', [])
    if len(indexes) > 5 or len(indexes) != len(set(indexes)) or any(type(i) is not int or i < 1 for i in indexes):
        raise ValueError('主图序号须为不重复的正整数，最多5个')


def run(task):
    validate_task(task)
    url, item_id = source_url(task['url'])
    settings = dict(task['settings'], generic_mode=True)
    shop_key = hashlib.sha256(settings['shop_name'].encode()).hexdigest()[:16]
    directory = ROOT / 'output' / 'tasks' / shop_key / item_id
    directory.mkdir(parents=True, exist_ok=True)
    journal = directory / 'submission.json'
    if task['mode'] == 'publish' and journal.exists():
        raise ValueError('此店铺/来源商品已有提交记录，请先到后台核对，禁止重复运行发布：' + str(journal))
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(ROOT / '.shop-profiles' / shop_key), channel='chrome', headless=False, no_viewport=True)
        try:
            product = collect(context, context.new_page(), url, directory)
            settings['title'] = settings.get('title') or product['title']
            settings['main_image_indexes'] = settings.get('main_image_indexes') or list(range(1, min(5,len(product['main_images']))+1))
            settings['description_paragraphs'] = settings.get('description_paragraphs') or [settings['title']]
            plan = make_plan(product, settings)
            (directory / 'target-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
            page = fill_review_draft(context, product, settings, directory)
            if task['mode'] == 'publish':
                result = publish_once(page, plan, settings, journal, directory)
                print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            print('结果目录：' + str(directory), flush=True)
        except Exception as error:
            (directory / 'error.txt').write_text(str(error), encoding='utf-8')
            print('停止：' + str(error), flush=True)
            raise
        finally:
            input('浏览器已保留。检查完成后按回车关闭：')
            context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('task', type=Path)
    args = parser.parse_args()
    run(json.loads(args.task.read_text(encoding='utf-8-sig')))
