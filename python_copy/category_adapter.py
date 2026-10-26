"""Discover category property controls; stop on ambiguous/unsupported controls."""
from playwright.sync_api import expect
from draft_basics import select_virtual_option


def property_fields(page):
    return page.locator('[id^="struct-p-"]').evaluate_all('''ns => ns.filter(n =>
      n.getClientRects().length && !n.querySelector('[id^="struct-p-"]')).map(n => {const w=n.closest('.sell-component-info-wrapper-wrap') || n; return ({
        id:n.id,
        name:w.querySelector('.sell-component-info-wrapper-label')?.textContent.trim() || '',
        required:!!w.querySelector('.sell-component-info-wrapper-required'),
        value:[...n.querySelectorAll('input:not([type=hidden]),textarea,.next-select-values em')].map(x=>x.value || x.textContent.trim()).filter(Boolean).join(' / ')
      })})''')


def fill_attributes(page, settings, strict=True):
    values = dict(settings.get('attributes', {}))
    values['品牌'] = settings['brand']
    # Re-discover after each change: one property can add/remove dependent fields.
    done = set()
    for _ in range(100):
        fields = property_fields(page)
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
    fields = property_fields(page)
    if not fields or any(not f['name'] for f in fields):
        raise ValueError('当前类目属性结构未识别，停止自动填写')
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
