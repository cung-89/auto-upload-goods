"""Verified basic-field adapter, not a complete product publisher."""
from urllib.parse import urlparse


def select_virtual_option(page, text):
    """Taobao province lists render incrementally while scrolling."""
    target = page.get_by_title(text, exact=True)
    for _ in range(20):
        if target.count() == 1 and target.is_visible():
            target.click()
            return
        by_text = page.get_by_text(text, exact=True)
        visible = [n for n in by_text.all() if n.is_visible()]
        if len(visible) == 1:
            visible[0].click()
            return
        options = page.locator('.options-item:visible')
        if not options.count():
            page.wait_for_timeout(250)
            continue
        moved = options.last.evaluate('''n => {
          for (let e = n.parentElement; e; e = e.parentElement) {
            if (e.scrollHeight > e.clientHeight + 20 && e.clientHeight > 0 &&
                ['auto', 'scroll'].includes(getComputedStyle(e).overflowY)) {
              const before = e.scrollTop;
              e.scrollTop = e.scrollHeight;
              return e.scrollTop !== before;
            }
          }
          return false;
        }''')
        page.wait_for_timeout(300)
        if not moved:
            break
    raise ValueError(f'未找到唯一选项：{text}')


def prepare_basic_draft(context, product, settings):
    category = settings.get('category')
    title = settings.get('title') or product['title']
    brand = settings.get('brand')
    if settings.get('generic_mode'):
        from category_adapter import prepare_category
        return prepare_category(context, product, settings)
    if category != '水产肉类/新鲜蔬果/熟食>新鲜蔬菜/包装新鲜蔬菜>番薯':
        raise ValueError('请使用通用工具入口配置其他类目')
    if not brand or sum(1 if ord(c) < 128 else 2 for c in title) > 60:
        raise ValueError('品牌缺失或标题超过60字符')
    attributes = {a['name']: a['value'] for a in product['source_attributes']}
    required = ['产地', '省份', '城市', '包装方式']
    if any(not attributes.get(k) for k in required):
        raise ValueError('来源商品产地/包装属性不完整，不能选择目标类目关键属性')
    page = context.new_page()
    page.goto('https://item.upload.taobao.com/sell/ai/category.htm', wait_until='domcontentloaded')
    search = page.get_by_placeholder('可输入产品名称、类目关键词、条码信息')
    try:
        search.wait_for(timeout=15000)
    except Exception:
        input('请在浏览器完成卖家登录，进入发布类目页后按回车：')
    search.fill('木薯')
    page.get_by_role('button', name='搜索', exact=True).click()
    page.get_by_text(category, exact=True).click()
    for selector, key in [('#struct-p-21299', '产地'),
                          ('#struct-p-21299-122450261', '省份'),
                          ('#struct-p-21299-122450261-20741', '城市'),
                          ('#struct-p-6939376', '包装方式')]:
        page.locator(selector).get_by_role('combobox').click()
        select_virtual_option(page, attributes[key])
    page.get_by_role('button', name='确认，下一步', exact=True).click()
    title_input = page.get_by_placeholder('最多允许输入30个汉字（60字符）')
    title_input.wait_for(timeout=60000)
    title_input.fill(title)
    brand_input = page.locator('#struct-p-20000').get_by_role('combobox')
    brand_input.fill(brand)
    page.locator('.options-search > .next-input > input').fill(brand)
    page.get_by_title(brand, exact=True).click()
    # Brand selection refreshes the category/SKU schema asynchronously.
    # Let that refresh finish before opening the SKU builder.
    page.wait_for_timeout(5000)
    if title_input.input_value() != title or brand_input.input_value() != brand:
        raise ValueError('标题或品牌回读不一致')
    print('已填入并核对标题和品牌。图片/SKU/物流尚未填写；未保存、未提交。')
    return page
