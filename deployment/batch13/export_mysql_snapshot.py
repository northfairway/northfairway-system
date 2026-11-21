"""Read-only, consistent MySQL snapshot to newline-delimited JSON.

Use on a private workstation, not inside a public web request. The output includes
sensitive homeowner, renter, and financial data; secure it and delete after use.
Requires: pip install PyMySQL

Example:
 MYSQL_HOST=127.0.0.1 MYSQL_USER=... MYSQL_PASSWORD=... MYSQL_DATABASE=... \
 python deployment/batch13/export_mysql_snapshot.py --out /secure/private/snapshot

No PostgreSQL import is attempted here because the target schema and business
queries must first be validated. Snapshot is for controlled migration and audit.
"""
import argparse, datetime, decimal, hashlib, json, os, pathlib
import pymysql
import pymysql.cursors

def serial(value):
 if isinstance(value,decimal.Decimal): return str(value)
 if isinstance(value,(datetime.datetime,datetime.date,datetime.time)): return value.isoformat()
 if isinstance(value,(bytes,bytearray)): return {'_hex':value.hex()}
 return value

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--out',required=True);args=ap.parse_args()
 output=pathlib.Path(args.out).resolve()
 output.mkdir(mode=0o700,parents=True,exist_ok=True)
 cn=pymysql.connect(host=os.environ['MYSQL_HOST'],port=int(os.getenv('MYSQL_PORT','3306')),user=os.environ['MYSQL_USER'],password=os.environ['MYSQL_PASSWORD'],database=os.environ['MYSQL_DATABASE'],autocommit=False,cursorclass=pymysql.cursors.DictCursor,charset='utf8mb4')
 manifest={'format':'NFH_B13_READ_ONLY_SNAPSHOT_V1','source_database':os.environ['MYSQL_DATABASE'],'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'tables':[]}
 try:
  with cn.cursor() as cur:
   cur.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
   cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
   cur.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE=%s ORDER BY TABLE_NAME',(os.environ['MYSQL_DATABASE'],'BASE TABLE'))
   tables=[r['TABLE_NAME'] for r in cur.fetchall()]
   for table in tables:
    # table names are obtained from information_schema and quote-escaped; never from external input
    q='`'+table.replace('`','``')+'`'; dest=output/(table+'.jsonl')
    if '/' in table or '\\' in table or table in ('.','..'): raise ValueError('Unexpected table name')
    digest=hashlib.sha256(); count=0
    with dest.open('wb') as f:
     cur.execute('SELECT * FROM '+q)
     while True:
      rows=cur.fetchmany(512)
      if not rows:break
      for row in rows:
       blob=(json.dumps(row,default=serial,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
       f.write(blob);digest.update(blob);count+=1
    os.chmod(dest,0o600)
    manifest['tables'].append({'table':table,'rows':count,'sha256':digest.hexdigest(),'file':dest.name})
  cn.rollback()  # read-only consistent snapshot; never commit data changes
 finally:cn.close()
 target=output/'manifest.json';target.write_text(json.dumps(manifest,indent=2),encoding='utf-8');os.chmod(target,0o600)
 print(f'Exported {len(manifest["tables"])} tables to {output}. Treat as highly sensitive data.')
if __name__=='__main__':main()
