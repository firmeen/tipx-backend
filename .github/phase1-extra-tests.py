import os,sys,json,tempfile,importlib
from pathlib import Path
os.environ.update({
 'AUTH_ENABLED':'true','AUTH_DB_AUTO_CREATE':'false','AUTH_DB_AUTO_SEED':'false',
 'TIPX_AUTO_CREATE_DIRS':'false','TIPX_DEBUG':'false',
 'TIPX_CORS_ALLOW_ORIGINS':'http://localhost:3000',
 'TIPX_TRUSTED_HOSTS':'localhost,127.0.0.1,testserver',
})
sys.path.insert(0,'.')
import config
from fastapi.testclient import TestClient
import app, api_routes, utils
client=TestClient(app.create_app())
checks={}
def c(k,v,d=''): checks[k]={'passed':bool(v),'detail':d}
c('auth_public_health',client.get('/api/health').status_code==200)
c('auth_public_status',client.get('/api/status').status_code==200)
c('auth_public_docs',client.get('/api/docs').status_code==200)
c('auth_public_openapi',client.get('/api/openapi.json').status_code==200)
c('auth_public_contract',client.get('/api/auth/contract').status_code==200)
r=client.get('/api/companies')
c('protected_api',r.status_code==401,r.text[:250])
# no path disclosure on public status/health
for path in ['/api/health','/api/status']:
 text=client.get(path).text
 c('no_path_leak_'+path.rsplit('/',1)[-1], 'C:/Users/' not in text and str(Path.cwd()) not in text,text[:250])
# business mysql source 501
config.USE_MYSQL_DATA_SOURCE=True; config.USE_EXCEL_DATA_SOURCE=False
r=api_routes.call_data_service('company','get_company_list',{})
c('mysql_business_501',r.get('meta',{}).get('status_code')==501,str(r))
# package security readiness
config.ENABLE_PACKAGE_ACCESS_TOKEN=True; config.SECRET_KEY=''; config.PACKAGE_TOKEN_SALT=''
v=config.validate_basic_config()
c('package_secret_validation',any(x.get('code')=='package_secret_missing' for x in v['errors']) and any(x.get('code')=='package_token_salt_missing' for x in v['errors']))
# failed build not cached
with tempfile.TemporaryDirectory() as td:
 old=utils.CACHE_DIR; utils.CACHE_DIR=Path(td)
 try:
  rr=utils.get_or_build_cache('failed_test',lambda:{'success':False,'message':'failed','data':{},'meta':{'status_code':500},'errors':[]},force_refresh=True)
  c('failed_cache_not_written',rr.get('cache_written') is False and not utils.get_cache_file_path('failed_test').exists(),str(rr))
 finally: utils.CACHE_DIR=old
config.CORS_ALLOW_ORIGINS=['*']
config.CORS_ALLOW_CREDENTIALS=True
v=config.validate_basic_config()
c('cors_wildcard_credentials_rejected',any(x.get('code')=='cors_wildcard_credentials' for x in v['errors']),str(v))
failed=[k for k,v in checks.items() if not v['passed']]
print(json.dumps({'results':checks,'failed':failed},indent=2))
raise SystemExit(1 if failed else 0)
