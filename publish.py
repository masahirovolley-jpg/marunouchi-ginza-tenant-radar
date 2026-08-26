"""Exchange a short-lived GitHub OIDC identity for a single result submission."""
import json
import os
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

SITE = 'https://marunouchi-ginza-tenant-radar.masahirovolley.chatgpt.site'

def publish():
    url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']+'&audience='+quote(SITE, safe='')
    req = Request(url, headers={'Authorization':'Bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with urlopen(req, timeout=30) as r:
        token = json.load(r)['value']
    data = (Path(__file__).parent/'data/latest.json').read_bytes()
    req = Request(SITE+'/api/collection', data=data, method='POST', headers={
        'Authorization':'Bearer '+token, 'Content-Type':'application/json'})
    with urlopen(req, timeout=60) as r:
        result = json.load(r)
    if not result.get('ok'):
        raise RuntimeError('Site did not accept the collection')
    print('Dashboard accepted collection: '+str(result.get('at')))

if __name__ == '__main__':
    publish()
