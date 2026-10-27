"""DOM regression tests in a local, headless Chrome; no seller requests."""
import unittest
from playwright.sync_api import sync_playwright
from category_adapter import property_fields, wait_for_property_fields, fill_attributes


class CategoryAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def test_delayed_fields_and_selected_value(self):
        self.page.set_content('''<script>setTimeout(()=>document.body.innerHTML=`
        <div class="sell-component-info-wrapper-wrap">
         <span class="sell-component-info-wrapper-label">产地</span>
         <span class="sell-component-info-wrapper-required">*</span>
         <div id="struct-p-1"><span class="next-select-values"><em>中国大陆</em></span><input value=""></div>
        </div>`,300)</script>''')
        fields = wait_for_property_fields(self.page, timeout_ms=3000, stable_ms=200)
        self.assertEqual(fields[0]['name'], '产地')
        self.assertEqual(fields[0]['value'], '中国大陆')
        self.assertTrue(fields[0]['required'])

    def test_label_associations_and_unchecked_checkbox(self):
        self.page.set_content('''<label for="variety">品种：</label>
        <div id="struct-p-1"><input id="variety" required></div>
        <span id="label2">包装方式</span><div id="struct-p-2"><input aria-labelledby="label2" type="checkbox" value="盒装"></div>''')
        fields = property_fields(self.page)
        self.assertEqual([f['name'] for f in fields], ['品种', '包装方式'])
        self.assertEqual(fields[1]['value'], '')

    def test_unnamed_field_does_not_pass(self):
        self.page.set_content('<div id="struct-p-9"><input></div>')
        with self.assertRaisesRegex(ValueError, '无法识别名称：struct-p-9'):
            wait_for_property_fields(self.page, timeout_ms=400)

    def test_empty_page_does_not_pass(self):
        self.page.set_content('<p>加载中</p>')
        with self.assertRaisesRegex(ValueError, '未发现可见属性控件'):
            wait_for_property_fields(self.page, timeout_ms=400)

    def test_chooser_known_ids_without_editor_labels(self):
        self.page.route('**/*', lambda route: route.fulfill(body='''
            <div id="struct-p-21299"><input></div>
            <div id="struct-p-6939376"><input></div>''', content_type='text/html'))
        self.page.goto('https://item.upload.taobao.com/sell/ai/category.htm')
        fields = wait_for_property_fields(self.page, timeout_ms=2000, stable_ms=200)
        self.assertEqual([f['name'] for f in fields], ['产地', '包装方式'])
        self.assertTrue(all(f['required'] for f in fields))
        with self.assertRaisesRegex(ValueError, '请在类目属性中补充：产地、包装方式'):
            fill_attributes(self.page, {'brand': '无品牌', 'attributes': {}})

    def test_chooser_fallback_does_not_apply_to_other_pages(self):
        self.page.set_content('<div id="struct-p-21299"><input></div>')
        self.assertEqual(property_fields(self.page)[0]['name'], '')

    def test_missing_required_is_still_blocked(self):
        self.page.set_content('<label for="kind">品种</label><div id="struct-p-1"><input id="kind" required></div>')
        with self.assertRaisesRegex(ValueError, '请在类目属性中补充：品种'):
            fill_attributes(self.page, {'brand':'无品牌','attributes':{}})
