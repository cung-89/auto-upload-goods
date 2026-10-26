"""Independent Taobao product collector. No extension or vendor service required.

The first adapter targets the observed 2025 SSR detail page. Unknown layouts fail
explicitly; this program never treats recommendation images as product images.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
EXTRACT = Path(__file__).with_name('extract_product.js').read_text(encoding='utf-8')


def source_url(value):
    value = value.replace('\\&', '&')
    parsed = urlparse(value)
    if parsed.hostname not in {'item.taobao.com', 'detail.tmall.com'}:
        raise ValueError('仅支持淘宝或天猫商品链接')
    item_id = parse_qs(parsed.query).get('id', [''])[0]
    if not re.fullmatch(r'\d+', item_id):
        raise ValueError('商品链接缺少有效 id')
    return f'https://{parsed.hostname}/item.htm?id={item_id}', item_id


def image_url(value):
    if not isinstance(value, str):
        raise ValueError('图片地址格式错误')
    value = 'https:' + value if value.startswith('//') else value
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not (parsed.hostname or '').endswith('.alicdn.com'):
        raise ValueError('图片不是已支持的阿里图片域名')
    return value


def price_of(offer):
    text = str(offer.get('priceText') or '')
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', text):
        raise ValueError(f'不是单一 SKU 价格：{text!r}')
    value = Decimal(text)
    money = offer.get('priceMoney')
    if money is not None:
        try:
            if Decimal(str(money)) / 100 != value:
                raise ValueError('价格显示值与分单位值不一致')
        except InvalidOperation as exc:
            raise ValueError('价格金额格式错误') from exc
    if value <= 0:
        raise ValueError('SKU 价格必须大于零')
    return format(value, '.2f')


def normalize(raw, url, detail_images):
    canonical, expected_id = source_url(url)
    item = raw.get('item', {})
    if str(item.get('itemId')) != expected_id:
        raise ValueError('采集商品 ID 与来源链接不一致')
    if not item.get('title') or not item.get('images'):
        raise ValueError('未取得商品标题或主图，不能生成完整商品')
    props = raw.get('properties', [])
    prop_ids = [p['id'] for p in props]
    if len(set(prop_ids)) != len(prop_ids):
        raise ValueError('重复的规格属性 ID')
    lookup = {}
    for p in props:
        for v in p['values']:
            key = (p['id'], v['id'])
            if key in lookup:
                raise ValueError('重复的规格值 ID')
            lookup[key] = {'property_id': p['id'], 'property': p['name'],
                           'value_id': v['id'], 'value': v['name'],
                           'image': image_url(v['image']) if v.get('image') else None}
    source_skus = raw.get('skus', [])
    if not source_skus:
        if props:
            raise ValueError('有规格属性但 SKU 清单为空')
        source_skus = [{'id': '0', 'path': ''}]
    rows, ids, paths = [], set(), set()
    for s in source_skus:
        sku_id = str(s['id'])
        pairs = [tuple(v.split(':', 1)) for v in s['path'].split(';') if v]
        path_key = tuple(sorted(pairs))
        if sku_id in ids or path_key in paths:
            raise ValueError('重复 SKU ID 或规格组合')
        ids.add(sku_id)
        paths.add(path_key)
        if sorted(p[0] for p in pairs) != sorted(prop_ids):
            raise ValueError(f'SKU {sku_id} 规格维度不完整')
        try:
            values = [lookup[pair] for pair in pairs]
        except KeyError as exc:
            raise ValueError(f'SKU {sku_id} 引用了未知规格值') from exc
        offer = raw.get('offers', {}).get(sku_id)
        if not offer:
            raise ValueError(f'SKU {sku_id} 缺少价格；不能套用最低价')
        rows.append({'source_sku_id': sku_id, 'values': values,
                     'price': price_of(offer), 'price_label': offer.get('priceLabel'),
                     'source_displayed_quantity': offer.get('displayedQuantity'),
                     'source_quantity_is_capped': bool(offer.get('moreQuantity')),
                     'target_stock': None})
    return {'schema_version': 1, 'source_url': canonical, 'source_item_id': expected_id,
            'captured_at': datetime.now(timezone.utc).isoformat(), 'title': item['title'],
            'main_images': list(dict.fromkeys(image_url(u) for u in item['images'])),
            'detail_images': [image_url(u) for u in detail_images],
            'properties': props, 'skus': rows, 'source_attributes': raw.get('attributes', []),
            'status': 'source_collected_target_not_filled',
            'needs_configuration': ['target_category', 'target_stock', 'shipping_template',
                                    'shipping_origin', 'required_attributes'],
            'notes': ['来源显示库存可能是展示上限，不视为实际可售库存。',
                      '来源价格保留页面标签，不推断优惠券后的成交价。',
                      '未提交、未创建淘宝商品。']}


def save_product(product, directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'product.json').write_text(json.dumps(product, ensure_ascii=False, indent=2), encoding='utf-8')
    with (directory / 'skus.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['来源SKU', '规格组合', '来源价格', '价格标签', '来源展示库存', '目标库存'])
        for row in product['skus']:
            writer.writerow([row['source_sku_id'], ' / '.join(v['value'] for v in row['values']),
                             row['price'], row['price_label'], row['source_displayed_quantity'], ''])


def download_images(product, directory, request):
    groups = {'main': product['main_images'], 'detail': product['detail_images'],
              'sku': list(dict.fromkeys(v['image'] for s in product['skus'] for v in s['values'] if v['image']))}
    manifest = []
    for group, urls in groups.items():
        for number, url in enumerate(urls, 1):
            response = request.get(url, timeout=60000)
            try:
                content_type = response.headers.get('content-type', '').split(';')[0]
                suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif'}.get(content_type)
                if not response.ok or not suffix:
                    raise ValueError(f'图片下载未成功：{group}/{number}，HTTP {response.status}')
                content = response.body()
                if not content:
                    raise ValueError('图片响应为空')
                relative = f'images/{group}/{number:03d}{suffix}'
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                manifest.append({'group': group, 'index': number, 'url': url, 'file': relative,
                                 'sha256': hashlib.sha256(content).hexdigest()})
            finally:
                response.dispose()
    (directory / 'images.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def collect(context, page, url, directory, interactive=True):
    canonical, item_id = source_url(url)
    page.goto(canonical, wait_until='domcontentloaded', timeout=60000)
    try:
        page.wait_for_function('() => !!window.__ICE_APP_CONTEXT__?.loaderData?.home?.data?.res?.item?.itemId', timeout=15000)
    except Exception:
        if not interactive:
            raise ValueError('需登录/验证，或当前商品页结构尚不支持')
        input('请在浏览器完成登录/验证并回到商品页，然后按回车：')
    raw = page.evaluate('(' + EXTRACT + ')()')
    if not raw or raw['item']['itemId'] != item_id:
        raise ValueError('未读取到指定商品结构；保留浏览器现场，不生成不完整数据')
    desc_url = raw['item'].get('descriptionUrl')
    if not desc_url:
        raise ValueError('未找到图文详情入口')
    desc_url = 'https:' + desc_url if desc_url.startswith('//') else desc_url
    parsed = urlparse(desc_url)
    if parsed.hostname != 'market.m.taobao.com' or parse_qs(parsed.query).get('id') != [item_id]:
        raise ValueError('图文详情地址与商品不匹配')
    detail = context.new_page()
    try:
        detail.goto(desc_url, wait_until='domcontentloaded', timeout=60000)
        detail.locator('img').first.wait_for(timeout=30000)
        # Trigger lazy loading, then check that the number of image elements stabilizes.
        last_count, stable = -1, 0
        for _ in range(30):
            detail.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
            detail.wait_for_timeout(500)
            count = detail.locator('img').count()
            stable = stable + 1 if count == last_count else 0
            last_count = count
            if stable >= 4:
                break
        if stable < 4:
            raise ValueError('图文详情仍在变化，无法确认采集完成')
        images = detail.locator('img').evaluate_all("ns => ns.map(n => n.getAttribute('data-src') || n.currentSrc || n.src)")
        product = normalize(raw, canonical, images)
        save_product(product, directory)
        download_images(product, directory, context.request)
        print(f'已采集 {len(product["skus"])} 个 SKU、{len(product["main_images"])} 张主图、{len(images)} 张详情图：{directory}')
        return product
    finally:
        detail.close()


def main():
    parser = argparse.ArgumentParser(description='独立 Python 淘宝/天猫商品采集，尚不提交商品')
    parser.add_argument('url', nargs='?', default='https://item.taobao.com/item.htm?id=745182817868')
    parser.add_argument('--snapshot', type=Path, help='从已脱敏的商品快照转换，无需浏览器登录')
    parser.add_argument('--download', action='store_true', help='快照模式同时下载图片')
    parser.add_argument('--draft-basics', action='store_true', help='采集后只填写类目关键属性、标题、品牌；不上传图片、不填写SKU、不提交')
    parser.add_argument('--draft', action='store_true', help='填写目标SKU、库存、物流、主图及详情，停留编辑页，不提交')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cdp', help='连接已开启调试端口的浏览器，例如 http://localhost:9222')
    parser.add_argument('--debug-port', type=int, help='联调时在本机开放 Chrome 调试端口；平时无需设置')
    args = parser.parse_args()
    if args.snapshot and args.draft_basics:
        parser.error('--draft-basics 需要浏览器采集模式，不能与 --snapshot 合用')
    canonical, item_id = source_url(args.url)
    directory = args.output or ROOT / 'output' / 'python-copy' / item_id
    from playwright.sync_api import sync_playwright
    product = None
    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
        product = normalize(snapshot['raw'], canonical, snapshot['detail_images'])
        save_product(product, directory)
        if args.download:
            with sync_playwright() as pw:
                request = pw.request.new_context()
                try:
                    download_images(product, directory, request)
                finally:
                    request.dispose()
        print(f'已转换 {len(product["skus"])} 个 SKU：{directory}')
        if not args.draft:
            return
    with sync_playwright() as pw:
        attached = bool(args.cdp)
        if attached:
            browser = pw.chromium.connect_over_cdp(args.cdp)
            context = browser.contexts[0]
        else:
            debug_args = [f'--remote-debugging-port={args.debug_port}', '--remote-debugging-address=127.0.0.1'] if args.debug_port else []
            context = pw.chromium.launch_persistent_context(str(ROOT / '.python-copy-profile'), channel='chrome', headless=False, no_viewport=True, args=debug_args)
        page = context.new_page()
        try:
            if product is None:
                product = collect(context, page, canonical, directory)
            if args.draft:
                from draft_product import fill_review_draft
                settings = json.loads(Path(__file__).with_name('target-settings.json').read_text(encoding='utf-8'))
                fill_review_draft(context, product, settings, directory)
            if args.draft_basics:
                from draft_basics import prepare_basic_draft
                settings = json.loads(Path(__file__).with_name('target-settings.json').read_text(encoding='utf-8'))
                prepare_basic_draft(context, product, settings)
        except Exception as error:
            print(f'流程停止：{error}', flush=True)
            raise
        finally:
            if not attached:
                input('按回车关闭采集浏览器：')
                context.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(f'停止：{error}', file=sys.stderr)
        sys.exit(1)
