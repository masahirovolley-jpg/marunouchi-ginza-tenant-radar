import unittest
from collector import extract, canonical

class ExtractTests(unittest.TestCase):
    def test_listing_and_no_food(self):
        s={'name':'飲食店ドットコム','type':'募集','area':'銀座','url':'https://www.inshokuten.com/bukken/'}
        html='<p>'+('公開物件情報 '*20)+'</p><a href="/bukken/bukkens/123">銀座6丁目 サロン居抜き 飲食不可</a><a href="/bukken/list">銀座の物件一覧</a>'
        items,_=extract(s,html,'2026-08-26T00:00:00+00:00')
        self.assertEqual(len(items),1)
        self.assertIn('飲食不可',items[0]['title'])
        self.assertEqual(items[0]['kind'],'募集候補')

    def test_temporary_and_external_excluded(self):
        s={'name':'Marunouchi.com','type':'施設公式','area':'丸の内','url':'https://www.marunouchi.com/'}
        html='<p>'+('施設ニュース '*20)+'</p><a href="/a">雑貨店の閉店のお知らせ</a><a href="/b">期間限定ショップ営業終了</a><a href="https://evil.test/">丸の内 閉店のお知らせ</a>'
        items,_=extract(s,html,'now')
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['area'],'丸の内')

    def test_block_page_not_empty_success(self):
        with self.assertRaises(ValueError):
            extract({'url':'https://example.com','type':'募集'},'Just a moment','now')

    def test_stable_id(self):
        s={'name':'飲食店ドットコム','type':'募集','area':'銀座','url':'https://www.inshokuten.com/'}
        html='<p>'+('公開物件 '*30)+'</p><a href="/bukken/bukkens/123">銀座6丁目 4階 サロン</a>'
        self.assertEqual(extract(s,html,'a')[0][0]['id'],extract(s,html,'b')[0][0]['id'])

    def test_nested_anchor_preserves_property_card(self):
        s={'name':'飲食店ドットコム','type':'募集','area':'銀座','url':'https://www.inshokuten.com/'}
        html='<p>'+('公開物件 '*30)+'</p><a href="/bukken/bukkens/399765">銀座6丁目 サロン 飲食店不可<a href="/help">ヘルプ</a>登録日：2026-08-26</a>'
        items,_=extract(s,html,'now')
        self.assertEqual(len(items),1)
        self.assertIn('飲食店不可',items[0]['title'])

if __name__=='__main__': unittest.main()
