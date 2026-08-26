"""Public-page monitor. No login, no browser evasion, no vacancy inference."""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, urlunsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).parent
UA = 'TenantRadar/1.0 (+https://marunouchi-ginza-tenant-radar.masahirovolley.chatgpt.site/)'
LIMIT = 2_000_000
REGION = re.compile(r'銀座|丸の内|有楽町|東京駅')
CLOSE = re.compile(r'閉店|営業終了|閉業|移転')
TEMP = re.compile(r'一時休業|臨時休業|休館日|POP.?UP|ポップアップ|催事|期間限定', re.I)


class SameHost(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme != 'https' or old.hostname != new.hostname:
            raise ValueError('別ホストへの転送のため取得保留')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit=LIMIT):
    if urlsplit(url).scheme != 'https':
        raise ValueError('HTTPS以外は取得しません')
    with build_opener(SameHost()).open(Request(url, headers={'User-Agent': UA}), timeout=20) as r:
        raw = r.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('取得サイズ上限超過')
        encoding = r.headers.get_content_charset()
        if not encoding:
            m = re.search(br'charset=["\s]*([\w-]+)', raw[:4096], re.I)
            encoding = m[1].decode('ascii') if m else 'utf-8'
        return raw.decode(encoding, errors='replace')


def robot_policy(url):
    p = urlsplit(url)
    robots_url = urlunsplit((p.scheme, p.netloc, '/robots.txt', '', ''))
    try:
        body = fetch(robots_url, 256_000)
    except HTTPError as e:
        if e.code == 404:
            return None
        raise ValueError('robots.txt確認失敗（取得保留）') from e
    robot = RobotFileParser()
    robot.parse(body.splitlines())
    return robot


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.parts, self.anchors, self.skip = [], [], [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if tag == 'a' and not self.skip:
            self.anchors.append([a.get('href', ''), []])
        if tag == 'img' and self.anchors and a.get('alt'):
            for anchor in self.anchors:
                anchor[1].append(a['alt'])

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
        if tag == 'a' and self.anchors:
            anchor = self.anchors.pop()
            self.links.append((anchor[0], ' '.join(anchor[1])))

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())
            for anchor in self.anchors:
                anchor[1].append(data.strip())


def canonical(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))


def extract(source, html, at):
    p = Page()
    p.feed(html)
    plain = ' '.join(p.parts)
    if len(plain) < 100 or re.search(r'Just a moment|Access Denied|アクセスが拒否|ロボットではない', plain[:2000], re.I):
        raise ValueError('本文が取得できない、またはアクセス制限')
    found = {}
    listing = source['type'] == '募集'
    for href, title in p.links:
        title = re.sub(r'\s+', ' ', title).strip()
        url = canonical(urljoin(source['url'], href))
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname != urlsplit(source['url']).hostname:
            continue
        if len(title) < 8 or len(title) > 6000:
            continue
        if listing:
            # Only property-detail URLs, never the region/category navigation.
            detail = re.search(r'/bukkens/\d+|/rent/\d+|/building/index/\d+|/detail[/_-]|/bukken/[^/]+/\d+', url)
            if not detail or not REGION.search(title):
                continue
            kind = '募集候補'
        else:
            if not CLOSE.search(title) or TEMP.search(title):
                continue
            if not REGION.search(title) and source['name'] not in ('Marunouchi.com', '西銀座公式', 'GINZA SIX', '銀座経済新聞'):
                continue
            kind = '閉店・移転候補'
        if listing:
            title = re.split(r'登録日[：:]|最寄り駅', title)[0].strip()
        title = title[:250]
        ident = hashlib.sha256((source['name']+'|'+url+('' if listing else '|'+title)).encode()).hexdigest()[:24]
        found[ident] = {'id':ident, 'title':title[:300], 'url':url, 'source':source['name'],
                        'area':'丸の内' if '丸の内' in title or source['area']=='丸の内' else '銀座',
                        'kind':kind, 'firstSeen':at, 'checkedAt':at,
                        'note':'公開ページのリンク見出しから自動抽出。本文・募集継続・閉店日・重複は未確認。'}
    # This monitor reports a successful page fetch, not exhaustive discovery.
    return list(found.values()), hashlib.sha256(plain.encode()).hexdigest()


def collect():
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    previous_file = ROOT/'data/latest.json'
    previous = json.loads(previous_file.read_text('utf-8')) if previous_file.exists() else {}
    previous_status = {s['name']:s for s in previous.get('sources', [])}
    retained = {c['id']:c for c in previous.get('candidates', [])}
    initial_ids = set(retained)
    statuses, policies = [], {}
    for source in json.loads((ROOT/'sources.json').read_text('utf-8')):
        status = {**source, 'at':at, 'status':'error', 'count':0, 'message':''}
        try:
            host = urlsplit(source['url']).hostname
            if host not in policies:
                policies[host] = robot_policy(source['url'])
            policy = policies[host]
            if policy and not policy.can_fetch(UA, source['url']):
                raise ValueError('robots.txtにより自動取得対象外')
            delay = max(1, (policy.crawl_delay(UA) or 1) if policy else 1)
            if delay > 20:
                raise ValueError('サイト指定の取得間隔により手動確認対象')
            time.sleep(delay)
            items, digest = extract(source, fetch(source['url']), at)
            for c in items:
                if c['id'] in retained:
                    c['firstSeen'] = retained[c['id']]['firstSeen']
                retained[c['id']] = c
            old = previous_status.get(source['name'], {}).get('digest')
            status.update(status='partial', count=len(items), digest=digest,
                          changed=bool(old and old != digest),
                          message='公開ページ取得。見出し抽出のみ・全件網羅ではありません。' + (' 本文に変更あり。' if old and old != digest else ''))
        except Exception as e:
            message = str(e) if isinstance(e, ValueError) else ('HTTP '+str(e.code) if isinstance(e, HTTPError) else '通信失敗・要手動確認')
            status['message'] = message[:250]
        statuses.append(status)
        print(source['name']+': '+status['status']+' / '+str(status['count']))
    candidates = sorted(retained.values(), key=lambda x:x['firstSeen'], reverse=True)[:300]
    report = {'version':1, 'at':at, 'sources':statuses, 'candidates':candidates,
              'newCount':len(set(retained)-initial_ids),
              'runId':os.environ.get('GITHUB_RUN_ID','local'),
              'coverage':'登録した公開ページを毎日2回確認。リンク見出しによる候補抽出と本文変更検知です。全ページ巡回・会員情報・検索エンジン調査は含みません。候補は空室や閉店の確定情報ではありません。'}
    previous_file.parent.mkdir(exist_ok=True)
    previous_file.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    return report


if __name__ == '__main__':
    collect()
