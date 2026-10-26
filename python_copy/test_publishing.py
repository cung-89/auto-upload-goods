import json
import tempfile
import unittest
from pathlib import Path
from publishing import reserve_submission
from run_task import validate_task
import test_copy_product as fixture_module
from copy_product import normalize
from target_plan import make_plan


class PublishingTests(unittest.TestCase):
    def task(self):
        return {'url':'https://item.taobao.com/item.htm?id=123','mode':'draft','settings':{
            'shop_name':'测试店铺','brand':'无品牌','category':'蔬菜>番薯','shipping_template':'包邮',
            'dispatch_time':'48小时内发货','stock_per_sku':88,'shipping_origin':{'province':'广西','city':'梧州'}}}

    def test_unknown_submission_cannot_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'submission.json'
            reserve_submission(path,{'status':'unknown'})
            with self.assertRaises(FileExistsError):reserve_submission(path,{'status':'retry'})
            self.assertEqual(json.loads(path.read_text())['status'],'unknown')

    def test_missing_shop_rejected(self):
        task=self.task();task['settings']['shop_name']=''
        with self.assertRaises(ValueError):validate_task(task)

    def test_invalid_price_rule_rejected_before_browser(self):
        task=self.task();task['settings']['price_rule']={'multiplier':'NaN'}
        with self.assertRaises(ValueError):validate_task(task)

    def test_duplicate_images_rejected(self):
        task=self.task();task['settings']['main_image_indexes']=[1,1]
        with self.assertRaises(ValueError):validate_task(task)

    def test_price_rule_and_override(self):
        fixture=fixture_module.CopyTests();fixture.setUp()
        source=normalize(fixture.raw,fixture.url,[])
        settings=self.task()['settings']
        settings.update(carrier='普通快递',price_rule={'multiplier':'1.5','addition':'1'},price_overrides={'100':'99.99'})
        plan=make_plan(source,settings)
        self.assertEqual([s['price'] for s in plan['skus']],['11.20','99.99'])


if __name__=='__main__':unittest.main()
