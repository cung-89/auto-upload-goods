"""Fill a reviewable Taobao editor. Deliberately contains no submit/save action."""
import html
import json
import re
from PIL import Image, ImageOps
from decimal import Decimal
from pathlib import Path
from playwright.sync_api import expect
from draft_basics import prepare_basic_draft


def sku_label(row):
    return ' / '.join(value['value'] for value in row['values']) or '默认规格'


def fill_skus(page, plan):
    labels = [sku_label(s) for s in plan['skus']]
    if len(set(labels)) != len(labels):
        raise ValueError('规格显示名重复')
    if page.locator('tr.sku-table-row').count():
        raise ValueError('目标页面已存在SKU；为避免覆盖已有商品，本流程只填空白发布页')
    page.get_by_role('button', name='+ 创建规格', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_role('radio', name='单层展示·自定义填写规格', exact=True).check()
    for index, label in enumerate(labels):
        if index:
            dialog.locator('button.add').click()
        fields = dialog.get_by_placeholder('输入规格')
        expect(fields).to_have_count(index + 1)
        fields.nth(index).fill(label)
        fields.nth(index).press('Tab')
    dialog.get_by_role('button', name='确认创建', exact=True).click()
    expect(page.locator('tr.sku-table-row')).to_have_count(len(labels))
    hint = page.get_by_role('button', name='我知道了', exact=True)
    if hint.is_visible():
        hint.click()
    for sku in plan['skus']:
        matching = [r for r in page.locator('tr.sku-table-row').all()
                    if r.locator('textarea[data-real=true]').input_value() == sku_label(sku)]
        if len(matching) != 1:
            raise ValueError('无法唯一匹配规格：' + sku_label(sku))
        row = matching[0]
        row.locator('[id$="-skuPrice"] input').fill(sku['price'])
        row.locator('[id$="-skuStock"] input').fill(str(sku['target_stock']))
        row.locator('[id$="-skuStock"] input').press('Tab')
    verify_skus(page, plan)


def verify_skus(page, plan):
    rows = page.locator('tr.sku-table-row').evaluate_all('''ns => ns.map(n => ({
        label:n.querySelector('textarea[data-real=true]').value,
        price:n.querySelector('[id$="-skuPrice"] input').value,
        stock:n.querySelector('[id$="-skuStock"] input').value
    }))''')
    expected = {sku_label(s): s for s in plan['skus']}
    if len(rows) != len(expected) or len({r['label'] for r in rows}) != len(rows):
        raise ValueError('SKU 数量不一致或有重复')
    for row in rows:
        sku = expected.get(row['label'])
        if not sku or Decimal(row['price']) != Decimal(sku['price']) or int(row['stock']) != sku['target_stock']:
            raise ValueError('SKU 回读不一致：' + row['label'])
    return rows


def fill_shipping(page, plan):
    ship = plan['shipping']
    origin = ship['shipping_origin']
    page.get_by_role('radio', name='大陆及港澳台', exact=True).check()
    page.get_by_role('radio', name='单一发货地', exact=True).check()
    area = page.locator('#struct-shippingArea')
    area.get_by_role('combobox').click()
    page.get_by_title(origin['province'], exact=True).click()
    page.get_by_title(origin['city'], exact=True).click()
    extract = page.locator('#struct-tbExtractWay')
    extract.get_by_role('checkbox', name=re.compile('使用物流配送')).check()
    extract.get_by_role('combobox').click()
    extract.get_by_role('combobox').fill(ship['shipping_template'])
    try:
        page.get_by_role('option', name=ship['shipping_template'], exact=True).wait_for(timeout=10000)
    except Exception as error:
        raise ValueError('当前店铺找不到运费模板：' + ship['shipping_template'] + '；请核对登录店铺和模板名称') from error
    page.get_by_role('option', name=ship['shipping_template'], exact=True).click()
    sf = extract.get_by_role('checkbox', name=re.compile('针对快递包邮区域使用顺丰'))
    if ship['carrier'] == '普通快递' and sf.count():
        sf.uncheck()
    expect(area).to_contain_text(origin['province'] + ' / ' + origin['city'])
    expect(extract).to_contain_text(ship['shipping_template'])


def selected_assets(plan, settings, directory):
    manifest = json.loads((directory / 'images.json').read_text(encoding='utf-8'))
    indexes = settings.get('main_image_indexes', [])
    if not indexes or len(indexes) > 5 or len(set(indexes)) != len(indexes):
        raise ValueError('请明确配置1到5张主图的来源序号')
    paths = []
    for index in indexes:
        matches = [m for m in manifest if m['group'] == 'main' and m['index'] == index]
        if len(matches) != 1:
            raise ValueError(f'缺少主图清单记录：{index}')
        source = (directory / matches[0]['file']).resolve()
        if directory.resolve() not in source.parents or not source.is_file():
            raise ValueError('素材路径不存在或超出商品目录')
        # The main-image upload route accepts JPEG reliably; retain originals separately.
        name = f'tb{plan["source_item_id"]}-main-{index:03d}-{matches[0]["sha256"][:8]}.jpg'
        target = directory / 'upload' / name
        target.parent.mkdir(exist_ok=True)
        with Image.open(source) as image:
            ImageOps.exif_transpose(image).convert('RGB').save(target, 'JPEG', quality=95)
        paths.append(target)
    return paths


def image_card(frame, filename):
    return frame.locator('[class*="PicList_pic_background"]').filter(
        has=frame.get_by_text(filename, exact=True))


def upload_main_images(page, paths):
    # The picture-space popover was clipped in 1000px height. Keep it fully on screen.
    page.set_viewport_size({'width': 1600, 'height': 1400})
    group = page.locator('#sell-field-mainImagesGroup')
    if group.locator('img').count():
        raise ValueError('目标已有主图，停止以避免覆盖或重复上传')
    group.locator('.empty-container').first.click()
    frame = page.frame_locator('iframe#mainImagesGroup')
    frame.get_by_text('本地上传', exact=True).click()
    frame.locator('input[type=file]').set_input_files([str(p) for p in paths])
    frame.get_by_text(f'{len(paths)} 个文件上传成功', exact=True).wait_for(timeout=120000)
    finish = frame.get_by_role('button', name='完成', exact=True)
    finish.click()
    expect(finish).to_be_hidden(timeout=30000)
    for index, path in enumerate(paths):
        if index:
            page.get_by_placeholder('最多允许输入30个汉字（60字符）').click()
            group.locator('.empty-container').first.click()
        frame = page.frame_locator('iframe#mainImagesGroup')
        card = image_card(frame, path.name)
        # Newly uploaded assets appear first; search by exact unique filename if needed.
        if not card.count():
            search = frame.get_by_placeholder('搜索图片名称')
            search.fill(path.name)
            search.press('Enter')
        expect(card).to_have_count(1, timeout=30000)
        card.locator('img').click()
        # Taobao's image picker performs the required 1:1 crop.
        expect(group.locator('img')).to_have_count(index + 1, timeout=60000)
    page.get_by_placeholder('最多允许输入30个汉字（60字符）').click()
    urls = group.locator('img').evaluate_all('ns => ns.map(n => n.src.replace(/\\.jpg_.*/, ".jpg"))')
    if any(not url.startswith('https://img.alicdn.com/') for url in urls):
        raise ValueError('上传后的图片地址不符合预期')
    return urls


def import_description(page, urls, settings):
    paragraphs = settings.get('description_paragraphs')
    if not paragraphs:
        raise ValueError('缺少目标详情文字')
    markup = ''.join('<p>' + html.escape(p) + '</p>' for p in paragraphs)
    markup += ''.join('<p><img src="' + html.escape(u, quote=True) + '" /></p>' for u in urls)
    page.get_by_text('源码导入', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_role('button', name='源码', exact=True).click()
    dialog.locator('textarea.cke_source').fill(markup)
    dialog.get_by_role('button', name='导入', exact=True).click()
    expect(dialog).to_be_hidden(timeout=30000)
    area = page.locator('#struct-descRepublicOfSell')
    expect(area).to_contain_text(paragraphs[-1])
    for url in urls:
        if not area.locator('img').evaluate_all('(ns,u)=>ns.some(n=>n.src.startsWith(u))', url):
            raise ValueError('详情图回读缺失')


def fill_review_draft(context, product, settings, directory):
    from target_plan import make_plan
    plan = make_plan(product, settings)
    if not plan['target_configuration_complete']:
        raise ValueError('目标配置不完整：' + ', '.join(plan['needs_configuration']))
    paths = selected_assets(plan, settings, directory)
    page = prepare_basic_draft(context, product, settings)
    try:
        fill_skus(page, plan)
        fill_shipping(page, plan)
        urls = upload_main_images(page, paths)
        import_description(page, urls, settings)
        rows = verify_skus(page, plan)
        expect(page.locator('#struct-p-20000').get_by_role('combobox')).to_have_value(settings['brand'])
        report = {'status': 'editor_filled_not_submitted', 'source_item_id': plan['source_item_id'],
                  'brand': settings['brand'], 'skus': rows, 'total_stock': sum(int(r['stock']) for r in rows),
                  'shipping': plan['shipping'], 'main_images': urls,
                  'scope': '标题/品牌/目标SKU/主图/详情/物流；未提交',
                  'remaining_review': ['产品产地沿用来源，发货地使用目标配置', '外包装/品种/系列等类目属性仍须确认', '平台默认服务承诺和发货时限须确认']}
        (directory / 'draft-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        page.screenshot(path=str(directory / 'draft-filled.png'), full_page=True)
        print('编辑页已填写并核对，未保存或提交。仍须核对报告中的类目属性与服务承诺。')
        return page
    except Exception:
        page.screenshot(path=str(directory / 'draft-error.png'), full_page=True)
        raise
