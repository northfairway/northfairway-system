"""Verify count and SHA-256 hashes for exported JSONL files, offline."""
import argparse,hashlib,json,pathlib
p=argparse.ArgumentParser();p.add_argument('snapshot_dir');a=p.parse_args()
root=pathlib.Path(a.snapshot_dir);manifest=json.loads((root/'manifest.json').read_text()); failures=[]
for item in manifest['tables']:
 file=root/item['file']; sha=hashlib.sha256();n=0
 with file.open('rb') as src:
  for line in src:sha.update(line);n+=1
 if sha.hexdigest()!=item['sha256'] or n!=item['rows']: failures.append(item['table'])
print(f'Checked {len(manifest["tables"])} tables; mismatches: {len(failures)}')
if failures:raise SystemExit('FAILED: '+', '.join(failures))
