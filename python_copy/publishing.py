"""One-shot publishing with a durable no-retry journal."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import expect
from category_adapter import property_fields
from draft_product import verify_skus


def reserve_submission(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation is intentional: unknown outcomes must never be retried.
    with path.open('x', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.flush()
        import os
        os.fsync(handle.fileno())


def publish_once(page, plan, settings, journal, directory):
    expect(page.get_by_text(settings['shop_name'], exact=True)).to_be_visible()
    expect(page.get_by_placeholder('最多允许输入30个汉字（60字符）')).to_have_value(plan['title'])
    verify_skus(page, plan)
    missing = [f['name'] for f in property_fields(page) if f['required'] and not f['value']]
    if missing:
        raise ValueError('必填属性未完成：' + '、'.join(missing))
    expect(page.locator('#struct-p-20000').get_by_role('combobox')).to_have_value(settings['brand'])
    expect(page.locator('#struct-shippingArea')).to_contain_text(settings['shipping_origin']['province'] + ' / ' + settings['shipping_origin']['city'])
    expect(page.locator('#struct-tbExtractWay').get_by_role('combobox')).to_have_attribute('aria-valuetext', settings['shipping_template'])
    expect(page.locator('#sell-field-mainImagesGroup img')).to_have_count(len(settings['main_image_indexes']))
    expect(page.locator('#struct-descRepublicOfSell')).to_contain_text(settings['description_paragraphs'][-1])
    page.get_by_role('radio', name=settings['dispatch_time'], exact=True).check()
    page.get_by_role('radio', name='立刻上架', exact=True).check()
    # Do not enroll in the default promotional discount program.
    promotion = page.get_by_role('radio', name='放弃本次机会', exact=True)
    if promotion.count():
        promotion.check()
    errors = page.locator('.next-form-item-help-error:visible,[aria-invalid=true]:visible')
    if errors.count():
        raise ValueError('页面存在校验错误，请检查编辑页')
    success = page.get_by_text('商品提交成功', exact=False)
    if success.count() and success.first.is_visible():
        raise ValueError('当前页面已经显示提交成功，拒绝重复提交')
    page.screenshot(path=str(directory / 'before-publish.png'), full_page=True)
    record = {'status':'submission_started_outcome_unknown', 'source_item_id':plan['source_item_id'],
              'shop':settings['shop_name'], 'started_at':datetime.now(timezone.utc).isoformat()}
    reserve_submission(journal, record)
    try:
        page.get_by_role('button', name='提交宝贝信息', exact=True).click()
        success.first.wait_for(timeout=60000)
        links = page.locator('a[href]').evaluate_all('(ns)=>ns.map(n=>n.href)')
        candidates = set()
        for url in links:
            parsed = urlparse(url)
            item_id = parse_qs(parsed.query).get('id', [''])[0]
            if parsed.hostname in {'item.taobao.com', 'detail.tmall.com'} and re.fullmatch(r'\d+', item_id):
                candidates.add('https://' + parsed.hostname + '/item.htm?id=' + item_id)
        record['status'] = 'platform_reported_success_verification_pending'
        if len(candidates) == 1:
            record['product_url'] = candidates.pop()
            verify = page.context.new_page()
            verify.goto(record['product_url'], wait_until='domcontentloaded')
            expect(verify.locator('body')).to_contain_text(plan['title'], timeout=30000)
            verify.screenshot(path=str(directory / 'published-product.png'), full_page=True)
            record['title_verified'] = True
        record['remaining_verification'] = '前台 SKU、价格、物流及详情需核对；成功提示不等于全部字段核验通过'
        page.screenshot(path=str(directory / 'publish-result.png'), full_page=True)
    except Exception as error:
        record['error'] = str(error)
        raise RuntimeError('提交已尝试，结果须到卖家后台核对；程序禁止自动重试。' + str(error)) from error
    finally:
        journal.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record
