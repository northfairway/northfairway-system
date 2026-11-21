"""Batch 13 read-only source inventory. No application imports or database writes."""
from pathlib import Path
import ast, json, re, argparse
ROOT=Path(__file__).resolve().parent
PATTERNS={
 'mysql_driver':r'\bpymysql\b|\bmysql\.connector\b',
 'mysql_upsert':r'ON\s+DUPLICATE\s+KEY\s+UPDATE',
 'mysql_insert_ignore':r'INSERT\s+IGNORE',
 'mysql_date_format':r'DATE_FORMAT\s*\(',
 'mysql_group_concat':r'GROUP_CONCAT\s*\(',
 'mysql_ifnull':r'IFNULL\s*\(',
 'mysql_last_insert_id':r'LAST_INSERT_ID\s*\(',
 'mysql_backticks':r'`[A-Za-z_][A-Za-z_0-9]*`',
 'mysql_show':r'\bSHOW\s+(TABLES|COLUMNS|INDEX|CREATE)\b',
 'local_file_write':r'\.save\s*\(|open\s*\([^\n]*[\'\"](?:w|a|x)b?[\'\"]|os\.makedirs|mkdir\s*\(',
 'local_memory_auth':r'VERIFICATION_CODES|RESET_CODES|OTP_CODES',
 'scheduler':r'APScheduler|schedule\.|cron|run_monthly_billing|monthly_billing',
}
def run():
 findings=[]; imports={}; parse_errors=[]
 for path in sorted(ROOT.rglob('*.py')):
  if any(s in path.parts for s in ('__pycache__','.venv','venv')): continue
  if path.name=='batch13_audit.py': continue
  text=path.read_text(encoding='utf-8',errors='replace'); relative=str(path.relative_to(ROOT))
  try:
   tree=ast.parse(text)
   imports[relative]=sorted({node.names[0].name.split('.')[0] for node in ast.walk(tree) if isinstance(node,ast.Import) for _ in [0]}|{node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.module})
  except SyntaxError as e:parse_errors.append({'file':relative,'line':e.lineno,'message':e.msg})
  for name,pattern in PATTERNS.items():
   lines=[i for i,line in enumerate(text.splitlines(),1) if re.search(pattern,line,re.I)]
   if lines: findings.append({'file':relative,'category':name,'count_lines':len(lines),'sample_lines':lines[:15]})
 sql=[]
 for path in sorted(ROOT.rglob('*.sql')):
  text=path.read_text(encoding='utf-8',errors='replace')
  sql.append({'file':str(path.relative_to(ROOT)), 'bytes':len(text.encode()),'create_tables':len(re.findall(r'CREATE\s+TABLE',text,re.I)), 'auto_increment':len(re.findall(r'AUTO_INCREMENT',text,re.I)), 'enum':len(re.findall(r'\bENUM\s*\(',text,re.I)), 'engine_clause':len(re.findall(r'ENGINE\s*=',text,re.I))})
 return {'status':'SOURCE_AUDIT_ONLY_NOT_POSTGRES_COMPATIBLE', 'python_files_scanned':len(imports), 'sql_files_scanned':len(sql),'findings':findings,'sql_inventory':sql,'parse_errors':parse_errors}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',default=str(ROOT/'BATCH13_SOURCE_INVENTORY.json'));a=p.parse_args();data=run();Path(a.out).write_text(json.dumps(data,indent=2),encoding='utf-8');print(json.dumps({'python_files':data['python_files_scanned'],'sql_files':data['sql_files_scanned'],'findings':len(data['findings']),'parse_errors':len(data['parse_errors']),'output':a.out},indent=2))
