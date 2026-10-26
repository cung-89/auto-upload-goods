"""Local desktop task form. No server and no password storage."""
import json
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from run_task import validate_task

ROOT = Path(__file__).resolve().parent.parent


class App:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.vars = {}
        root.title('淘宝商品复制与上架')
        root.geometry('840x890')
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        fields = [
            ('url','商品链接',''), ('shop_name','目标店铺名称',''),
            ('category','完整类目路径（用 > 分隔）',''), ('brand','品牌','无品牌'),
            ('stock_per_sku','每规格库存','88'), ('province','发货省','广西'),
            ('city','发货市','梧州'), ('shipping_template','运费模板','包邮'),
            ('dispatch_time','发货时限','48小时内发货'),
            ('title','商品标题（留空沿用来源）',''),
            ('multiplier','售价倍率','1'), ('addition','每规格加价（元）','0'),
            ('main_image_indexes','主图序号（逗号分隔，留空取前5张）','')]
        for row,(key,label,default) in enumerate(fields):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=4)
            self.vars[key]=tk.StringVar(value=default)
            if key=='dispatch_time':
                entry=ttk.Combobox(frame,textvariable=self.vars[key],state='readonly',values=['24小时内发货','48小时内发货','大于48小时发货'])
            else:
                entry=ttk.Entry(frame,textvariable=self.vars[key])
            entry.grid(row=row,column=1,sticky='ew',padx=10)
        row=len(fields)
        ttk.Label(frame,text='类目属性 JSON（按页面名称填写，缺项会提示）').grid(row=row,column=0,columnspan=2,sticky='w')
        self.attrs=tk.Text(frame,height=5)
        self.attrs.grid(row=row+1,column=0,columnspan=2,sticky='ew')
        self.attrs.insert('1.0','{}')
        ttk.Label(frame,text='详情文字（每行一段，留空用标题；配选中的主图）').grid(row=row+2,column=0,columnspan=2,sticky='w')
        self.desc=tk.Text(frame,height=3)
        self.desc.grid(row=row+3,column=0,columnspan=2,sticky='ew')
        ttk.Label(frame,text='规格调整 JSON（可选：改名、排除来源 SKU、指定价格）').grid(row=row+4,column=0,columnspan=2,sticky='w')
        self.advanced=tk.Text(frame,height=3)
        self.advanced.grid(row=row+5,column=0,columnspan=2,sticky='ew')
        self.advanced.insert('1.0','{}')
        buttons=ttk.Frame(frame)
        buttons.grid(row=row+6,column=0,columnspan=2,pady=14)
        ttk.Button(buttons,text='加载店铺配置',command=self.load).pack(side='left',padx=4)
        ttk.Button(buttons,text='保存店铺配置',command=self.save).pack(side='left',padx=4)
        ttk.Button(buttons,text='仅填写检查',command=lambda:self.start('draft')).pack(side='left',padx=4)
        ttk.Button(buttons,text='填写并自动上架',command=lambda:self.start('publish')).pack(side='left',padx=4)
        self.status=tk.StringVar(value='运行时会打开 Chrome 和日志窗口；登录/验证后在日志窗口按回车继续。')
        ttk.Label(frame,textvariable=self.status,wraplength=780).grid(row=row+7,column=0,columnspan=2,sticky='w')

    def settings(self):
        v={k:x.get().strip() for k,x in self.vars.items()}
        s={k:v[k] for k in ['shop_name','category','brand','shipping_template','dispatch_time','title']}
        s.update(stock_per_sku=int(v['stock_per_sku']),shipping_origin={'province':v['province'],'city':v['city']},carrier='普通快递',
                 price_rule={'multiplier':v['multiplier'],'addition':v['addition']},
                 attributes=json.loads(self.attrs.get('1.0','end')),
                 description_paragraphs=[x.strip() for x in self.desc.get('1.0','end').splitlines() if x.strip()],
                 main_image_indexes=[int(x.strip()) for x in v['main_image_indexes'].replace('，',',').split(',') if x.strip()])
        extra=json.loads(self.advanced.get('1.0','end'))
        if not isinstance(extra,dict) or set(extra)-{'sku_value_names','excluded_source_skus','price_overrides'}:
            raise ValueError('规格调整仅支持 sku_value_names、excluded_source_skus、price_overrides')
        s.update(extra)
        return s

    def save(self):
        try:
            settings=self.settings()
            # Product-specific content is intentionally excluded from shop presets.
            keep=['shop_name','brand','stock_per_sku','shipping_origin','shipping_template','carrier','dispatch_time','price_rule']
            path=filedialog.asksaveasfilename(defaultextension='.json',initialdir=str(ROOT/'python_copy'),title='保存店铺默认配置')
            if path:Path(path).write_text(json.dumps({k:settings[k] for k in keep},ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as error:messagebox.showerror('配置错误',str(error))

    def load(self):
        path=filedialog.askopenfilename(filetypes=[('店铺配置','*.json')])
        if not path:return
        try:
            s=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            for key in ['shop_name','brand','stock_per_sku','shipping_template','dispatch_time']:
                if key in s:self.vars[key].set(str(s[key]))
            for key in ['province','city']:
                if key in s.get('shipping_origin',{}):self.vars[key].set(s['shipping_origin'][key])
            for key in ['multiplier','addition']:
                if key in s.get('price_rule',{}):self.vars[key].set(str(s['price_rule'][key]))
        except Exception as error:messagebox.showerror('读取失败',str(error))

    def start(self,mode):
        try:
            if self.process and self.process.poll() is None:
                raise ValueError('已有任务正在运行，请先完成或关闭其日志窗口')
            task={'url':self.vars['url'].get().strip(),'settings':self.settings(),'mode':mode}
            validate_task(task)
            directory=ROOT/'output'/'task-configs'
            directory.mkdir(parents=True,exist_ok=True)
            path=directory/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
            path.write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
            self.process=subprocess.Popen([sys.executable,'-X','utf8','-u',str(Path(__file__).with_name('run_task.py')),str(path)],cwd=str(ROOT),creationflags=subprocess.CREATE_NEW_CONSOLE)
            self.status.set('任务已启动。请在 Chrome 完成登录，在日志窗口查看进度及缺项提示。')
        except Exception as error:messagebox.showerror('无法启动',str(error))


if __name__=='__main__':
    root=tk.Tk()
    App(root)
    root.mainloop()
