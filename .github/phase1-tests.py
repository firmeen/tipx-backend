import os, sys, json, warnings, importlib, tempfile
from pathlib import Path
os.environ.update({
    'AUTH_ENABLED':'false',
    'TIPX_AUTO_CREATE_DIRS':'false',
    'TIPX_DEBUG':'false',
    'TIPX_CORS_ALLOW_ORIGINS':'http://localhost:3000',
    'TIPX_TRUSTED_HOSTS':'localhost,127.0.0.1,testserver',
})
sys.path.insert(0,'.')

results={}

def check(name, cond, detail=''):
    results[name]={'passed':bool(cond),'detail':detail}

# compile/import
mods=['config','utils','schemas','security','company_policy_service','linkage_service','flood_spatial_service','entity_upload_service','map_graph_service','dashboard_package_service','data_quality','filter_engine','api_routes','auth.auth_service','auth.auth_routes','app']
for m in mods:
    importlib.import_module(m)
check('import_all',True)

import pandas as pd
import utils, filter_engine, config, api_routes
sample=[{'id':1,'name':'A','value':2},{'id':2,'name':'B','value':1}]
check('list_conversion',utils.dataframe_to_records(sample)==sample)
check('tuple_conversion',utils.dataframe_to_records(tuple(sample))==sample)
check('dataframe_conversion',utils.dataframe_to_records(pd.DataFrame(sample))==sample)
check('wrapper_conversion',utils.dataframe_to_records({'records':sample})==sample)
check('graph_conversion',len(utils.dataframe_to_records({'nodes':[{'id':'n'}],'edges':[{'id':'e'}]}))==2)
check('filter_self_test',filter_engine.run_filter_self_test().get('ready') is True)
check('empty_advanced',filter_engine.apply_advanced_filter(sample,{'logic':'AND','conditions':[],'groups':[]})==sample)
check('nested_filter',len(filter_engine.apply_advanced_filter(sample,{'logic':'OR','groups':[{'conditions':[{'field':'value','operator':'gt','value':'1','dtype':'number'}]},{'conditions':[{'field':'name','operator':'equals','value':'B'}]}]}))==2)

# path behavior
check('debug_default_off',config.DEBUG is False)
check('foreign_windows_path_preserved',str(config.FLOOD_OUTPUT_DIR).startswith('C:/'))
check('foreign_windows_path_incompatible',config.is_path_compatible_with_runtime(config.FLOOD_OUTPUT_DIR) is False)
check('no_fake_windows_path',not (Path.cwd()/str(config.FLOOD_OUTPUT_DIR)).exists())

# app/openapi/routes
from fastapi.testclient import TestClient
import app
application=app.create_app()
client=TestClient(application)
route_pairs=[]
for r in application.routes:
    for method in (getattr(r,'methods',set()) or set()):
        if method not in {'HEAD','OPTIONS'}:
            route_pairs.append((method,getattr(r,'path','')))
from collections import Counter
check('duplicate_method_path',not any(v>1 for v in Counter(route_pairs).values()))
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always')
    schema=application.openapi()
operation_ids=[]
for path_item in schema.get('paths',{}).values():
    for method,item in path_item.items():
        if isinstance(item,dict) and item.get('operationId'):
            operation_ids.append(item['operationId'])
check('duplicate_operation_id',len(operation_ids)==len(set(operation_ids)),str([str(w.message) for w in caught]))
check('cache_status_route',('/api/cache/status' in schema.get('paths',{})))

r=client.get('/api/health')
check('health_liveness',r.status_code==200 and r.json()['data']['status']=='alive',r.text[:300])
r=client.get('/api/status')
check('status_endpoint',r.status_code==200,r.text[:300])
check('docs_access',client.get('/api/docs').status_code==200)
check('openapi_access',client.get('/api/openapi.json').status_code==200)
check('auth_contract_public_disabled',client.get('/api/auth/contract').status_code==200)
check('invalid_int_query',client.get('/api/companies?page=abc').status_code==400,client.get('/api/companies?page=abc').text[:200])
check('invalid_bool_query',client.get('/api/companies?force_refresh=maybe').status_code==400)
check('invalid_sort_dir',client.get('/api/companies?sort_dir=sideways').status_code==400)
check('invalid_json',client.post('/api/filter/apply',content='{bad',headers={'content-type':'application/json'}).status_code==400)
check('non_object_json',client.post('/api/filter/apply',json=[]).status_code==422)

# exception sanitization directly
resp=api_routes.safe_call('missing_phase1_module','nope',{})
check('internal_exception_sanitized',resp['errors'][0]['message']=='Service function is not available.' and 'missing_phase1_module' not in resp['errors'][0]['message'])

# package token forwarding via monkeypatch current service functions
import dashboard_package_service as dps
captured={}
def fake_meta(package_id, context=None, token='', request_meta=None):
    captured.update(package_id=package_id,context=context,token=token,request_meta=request_meta)
    return {'success':True,'message':'ok','data':{'package_id':package_id},'meta':{},'errors':[]}
old=dps.get_public_package_meta
dps.get_public_package_meta=fake_meta
try:
    rr=client.get('/api/public/packages/pkg/meta',headers={'Authorization':'Bearer token-123','X-Request-ID':'req-1'})
    check('package_token_forwarding',rr.status_code==200 and captured.get('token')=='token-123' and captured.get('request_meta',{}).get('request_id')=='req-1',str(captured))
    captured.clear()
    rr=client.get('/api/public/packages/pkg/meta',headers={'X-TIPX-Package-Token':'header-token'})
    check('package_header_token_forwarding',rr.status_code==200 and captured.get('token')=='header-token',str(captured))
    captured.clear()
    rr=client.get('/api/public/packages/pkg/meta?token=query-token')
    check('package_query_token_forwarding',rr.status_code==200 and captured.get('token')=='query-token',str(captured))
finally:
    dps.get_public_package_meta=old

failed=[k for k,v in results.items() if not v['passed']]
print(json.dumps({'results':results,'failed':failed},indent=2,ensure_ascii=False))
raise SystemExit(1 if failed else 0)
