"""Static verification for Likida AI deploy deliverables.
Checks each changed file's type-appropriate validity:
  - docker-compose.prod.yml : PyYAML parse + compose semantics
  - railway.toml            : tomllib parse + deploy keys
  - scripts/deploy-railway.sh : bash -n syntax
  - .env*.example           : every non-comment line is KEY=VAL
"""
import subprocess
import sys
import tomllib
import yaml

base = '.'

ok = True

# 1. docker-compose.prod.yml
try:
    d = yaml.safe_load(open('docker-compose.prod.yml'))
    svcs = list(d['services'])
    assert svcs == ['postgres', 'api', 'nginx'], svcs
    api = d['services']['api']
    assert api['depends_on']['postgres']['condition'] == 'service_healthy'
    dsn = api['environment']['DATABASE_URL']
    assert dsn.startswith('postgresql://') and 'POSTGRES_PASSWORD' in dsn
    assert d['services']['postgres']['image'].startswith('postgres:15')
    assert set(d['volumes']) == {'postgres-data'}
    print('PASS docker-compose.prod.yml ->', svcs)
except Exception as e:
    ok = False
    print('FAIL docker-compose.prod.yml:', e)

# 2. railway.toml
try:
    t = tomllib.load(open('railway.toml', 'rb'))
    assert t['build']['builder'] == 'DOCKERFILE'
    assert 'uvicorn b2b_ai.api.app:app' in t['deploy']['startCommand']
    assert t['deploy']['healthcheckPath'] == '/health'
    print('PASS railway.toml -> health:', t['deploy']['healthcheckPath'])
except Exception as e:
    ok = False
    print('FAIL railway.toml:', e)

# 3. deploy-railway.sh
r = subprocess.run(['bash', '-n', 'scripts/deploy-railway.sh'])
print('PASS scripts/deploy-railway.sh (bash -n)' if r.returncode == 0
      else 'FAIL scripts/deploy-railway.sh')

# 4. .env*.example
for f in ('.env.example', '.env.production.example', '.env.railway.example'):
    n = 0
    bad = []
    for i, line in enumerate(open(f), 1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        if '=' not in s:
            bad.append((i, 'no =', s))
            continue
        k = s.split('=', 1)[0].strip()
        if not (k[0].isalpha() and k.replace('_', '').isalnum()):
            bad.append((i, 'bad key', k))
        n += 1
    if bad:
        ok = False
        print('FAIL %s (%d vars, %d bad): %s' % (f, n, len(bad), bad[:2]))
    else:
        print('PASS %s (%d vars)' % (f, n))

print('\nRESULT:', 'ALL PASS' if ok else 'FAILURES PRESENT')
sys.exit(0 if ok else 1)
