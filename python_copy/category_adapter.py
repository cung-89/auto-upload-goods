"""Discover category property controls; stop on ambiguous/unsupported controls."""
from playwright.sync_api import expect
import time
from draft_basics import select_virtual_option


def property_fields(page):
    fields = page.locator('[id^="struct-p-"]').evaluate_all(r'''ns => ns.filter(n =>
      n.getClientRects().length && !n.querySelector('[id^="struct-p-"]')).map(n => {
        const w=n.closest('.sell-component-info-wrapper-wrap') || n;
        const control=n.querySelector('input,textarea,select');
        const linkedIds=(control?.getAttribute('aria-labelledby') || n.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
        const linked=linkedIds.map(id=>document.getElementById(id)?.textContent.trim() || '').filter(Boolean).join(' ');
        const labels=[...document.querySelectorAll('label[for]')].filter(l=>l.htmlFor===n.id || (control?.id && l.htmlFor===control.id));
        const name=w.querySelector('.sell-component-info-wrapper-label')?.textContent.trim() || linked ||
          (labels.length===1 ? labels[0].textContent.trim() : '') || control?.getAttribute('aria-label') || '';
        return ({
        id:n.id,
        name:name.replace(/^\s*\*\s*/, '').replace(/[：:]\s*$/, '').trim(),
        required:!!w.querySelector('.sell-component-info-wrapper-required') || !!n.querySelector('[required],[aria-required="true"]'),
        value:[...n.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]),textarea,select,.next-select-values em,input[type=checkbox]:checked,input[type=radio]:checked')].map(x=>x.value || x.textContent.trim()).filter(Boolean).join(' / ')
      })})''')
    # The category chooser uses a different label layout from the editor.
    # These exact IDs were verified on the chooser; do not guess unknown IDs.
    from urllib.parse import urlparse
    location = urlparse(page.url)
    chooser_fields = {
        'struct-p-21299': '产地',
        'struct-p-21299-122450261': '省份',
        'struct-p-21299-122450261-20741': '城市',
        'struct-p-6939376': '包装方式',
    }
    if location.hostname == 'item.upload.taobao.com' and location.path == '/sell/ai/category.htm':
        for field in fields:
            if field['id'] in chooser_fields:
                if not field['name']:
                    field['name'] = chooser_fields[field['id']]
                field['required'] = True
    return fields


def wait_for_property_fields(page, timeout_ms=20000, stable_ms=1000):
    """Wait for named fields to settle, without treating an empty page as valid."""
    deadline = time.monotonic() + timeout_ms / 1000
    previous, since, fields = None, None, []
    while time.monotonic() < deadline:
        fields = property_fields(page)
        signature = tuple((f['id'], f['name'], f['required'], f['value']) for f in fields)
        now = time.monotonic()
        if fields and all(f['name'] for f in fields):
            if signature != previous:
                since = now
            elif since is not None and (now - since) * 1000 >= stable_ms:
                return fields
        else:
            since = None
        previous = signature
        page.wait_for_timeout(200)
    if not fields:
        raise ValueError('等待类目属性超时：未发现可见属性控件。可能尚未进入属性页、加载失败或当前类目结构未适配')
    unnamed = [f['id'] for f in fields if not f['name']]
    if unnamed:
        raise ValueError('发现属性控件但无法识别名称：' + '、'.join(unnamed))
    raise ValueError('类目属性持续刷新，尚未稳定，请检查页面')


def fill_attributes(page, settings, strict=True):
    values = dict(settings.get('attributes', {}))
    values['品牌'] = settings['brand']
    # Re-discover after each change: one property can add/remove dependent fields.
    done = set()
    for _ in range(100):
        fields = wait_for_property_fields(page)
        pending = [f for f in fields if f['name'] in values and f['id'] not in done]
        if not pending:
            break
        field = pending[0]
        block = page.locator('[id="' + field['id'] + '"]')
        value = str(values[field['name']])
        combo = block.get_by_role('combobox')
        if combo.count() == 1:
            combo.click()
            search = page.locator('.options-search > .next-input > input:visible')
            if search.count() == 1:
                search.fill(value)
            try:
                select_virtual_option(page, value)
            except ValueError:
                # Only explicitly free-text controls may accept arbitrary text.
                if combo.get_attribute('aria-autocomplete') != 'none':
                    raise ValueError('属性选项不匹配：' + field['name'] + '=' + value)
                combo.fill(value)
                combo.press('Tab')
        else:
            inputs = block.locator('input:not([type=hidden]):not([type=radio]):not([type=checkbox]),textarea')
            if inputs.count() != 1:
                raise ValueError('尚未适配该属性控件：' + field['name'])
            inputs.fill(value)
            inputs.press('Tab')
        done.add(field['id'])
        page.wait_for_timeout(500)
        if field['name'] == '品牌':
            page.wait_for_timeout(5000)
    fields = wait_for_property_fields(page)
    missing = [f['name'] or f['id'] for f in fields if f['required'] and not f['value']]
    if strict and missing:
        raise ValueError('请在类目属性中补充：' + '、'.join(missing))
    return fields


def prepare_category(context, product, settings):
    page = context.new_page()
    page.goto('https://item.upload.taobao.com/sell/ai/category.htm', wait_until='domcontentloaded')
    search = page.get_by_placeholder('可输入产品名称、类目关键词、条码信息')
    try:
        search.wait_for(timeout=15000)
    except Exception:
        input('请登录目标卖家店铺，进入选择类目页后按回车：')
    expect(page.get_by_text(settings['shop_name'], exact=True)).to_be_visible(timeout=15000)
    category = settings['category']
    search.fill(category.split('>')[-1])
    page.get_by_role('button', name='搜索', exact=True).click()
    page.get_by_text(category, exact=True).click()
    fill_attributes(page, settings)
    page.get_by_role('button', name='确认，下一步', exact=True).click()
    title = page.get_by_placeholder('最多允许输入30个汉字（60字符）')
    title.wait_for(timeout=60000)
    title.fill(settings.get('title') or product['title'])
    fill_attributes(page, settings)
    expect(title).to_have_value(settings.get('title') or product['title'])
    return page
