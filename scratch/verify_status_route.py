import sys

sys.path.insert(0, '/home/sayam/Desktop/TrustFL')
sys.path.insert(0, '/home/sayam/Desktop/TrustFL/apps')

from fastapi.testclient import TestClient

from apps.api.api.db.models import Base
from apps.api.api.db.session import engine
from apps.api.main import app

client = TestClient(app)
Base.metadata.create_all(bind=engine)

client.post('/federations/', json={'id': 'fed1', 'name': 'F', 'min_clients': 1, 'max_rounds': 1})
r = client.post('/rounds/', json={'federation_id': 'fed1', 'round_number': 1, 'model_version': 'v1'})
round_id = r.json()['data']['id']
u = client.post('/updates/', json={'id': 'upd1', 'round_id': round_id, 'client_id': 'c1', 'artifact_hash': 'h', 'nonce': 'n'})
print('submit:', u.status_code, u.json()['data']['status'])
res = client.put('/updates/upd1/status', json={'status': 'AGGREGATED'})
print('status:', res.status_code, res.json()['data']['status'])
assert res.status_code == 200
assert res.json()['data']['status'] == 'AGGREGATED'
res = client.put('/updates/nope/status', json={'status': 'AGGREGATED'})
print('missing:', res.status_code)
assert res.status_code == 404
print('ALL OK')
Base.metadata.drop_all(bind=engine)
