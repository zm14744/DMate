"""Import exact conversation originals and enforce complete-corpus provenance.

Input is an explicit index, not inferred filename adjacency. Re-drawings, public
PDF re-crops and mock responses cannot satisfy the historical-corpus gate.
No network/API calls. Original files are copied byte-for-byte and SHA256 checked.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

DIMENSIONS=('graph_accuracy','question_text','formula_rendering','description_accuracy',
            'description_uniformity','figure_separation')
STATUSES={'not_evaluated','pass','partial','fail','unverifiable'}


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_child(root,value):
    path=(root/str(value)).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'Missing or outside source directory: {value}')
    return path


def import_index(index_path,destination):
    index_path=Path(index_path).resolve(); source=index_path.parent
    index=json.loads(index_path.read_text(encoding='utf-8'))
    destination=Path(destination).resolve(); destination.mkdir(parents=True,exist_ok=True)
    manifest_path=destination/'manifest.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        'schema':'dmate.real-corpus/1','scope':'all_user_conversation_graph_originals',
        'enumeration_complete':False,'expected_case_count':None,'expected_batch_ids':[],
        'cases':[],'missing_materials':[]}
    used={c['id'] for c in manifest['cases']}
    planned=[]
    # Validate all referenced sources before writing anything.
    for row in index.get('cases',[]):
        cid=row.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',cid) or cid in used:
            raise ValueError('Invalid or duplicate case ID: '+cid)
        if row.get('source_kind') not in ('conversation_original','user_original_repository'):
            raise ValueError('Historical corpus requires actual user originals')
        original=safe_child(source,row['image'])
        if original.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.gif'):
            raise ValueError('Unsupported original image type')
        actual=digest(original)
        if row.get('sha256') and actual!=row['sha256']:
            raise ValueError('Original hash mismatch: '+cid)
        sources=[original]
        for field in ('original_ocr','ground_truth'):
            if row.get(field): sources.append(safe_child(source,row[field]))
        planned.append((row,sources,actual));used.add(cid)
    for row,sources,actual in planned:
        cid=row['id']; folder=destination/'cases'/cid
        if folder.exists(): raise ValueError('Case directory exists: '+cid)
        folder.mkdir(parents=True)
        original=sources[0]; original_name='original'+original.suffix.lower()
        shutil.copyfile(original,folder/original_name)
        record={'id':cid,'batch_id':row.get('batch_id'),'institution':row.get('institution'),
                'source_kind':row['source_kind'],'conversation_id':row.get('conversation_id'),
                'message_id':row.get('message_id'),'original_filename':original.name,
                'image':str((folder/original_name).relative_to(destination)),'sha256':actual,
                'original_ocr':None,'ground_truth':None,
                'ground_truth_independently_reviewed':False,'evaluation':str((folder/'evaluation.json').relative_to(destination))}
        for field in ('original_ocr','ground_truth'):
            if row.get(field):
                src=safe_child(source,row[field]);target=folder/(field+src.suffix.lower())
                shutil.copyfile(src,target); record[field]=str(target.relative_to(destination))
        if record['ground_truth']:
            record['ground_truth_independently_reviewed']=row.get('ground_truth_independently_reviewed') is True
        evaluations={'case_id':cid,'original_sha256':actual,
                     'dimensions':{d:{'status':'not_evaluated','evidence':[],'notes':''} for d in DIMENSIONS}}
        (folder/'evaluation.json').write_text(json.dumps(evaluations,ensure_ascii=False,indent=2))
        manifest['cases'].append(record)
    # Import cannot declare completeness. That requires reconciling every image
    # and OCR result against the original conversation inventory.
    manifest['enumeration_complete']=False
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest


def validate_corpus(manifest_path,*,full=False):
    manifest_path=Path(manifest_path).resolve(); root=manifest_path.parent
    data=json.loads(manifest_path.read_text());issues=[];seen=set();batches=set()
    cases=data.get('cases') or []
    if full:
        if data.get('enumeration_complete') is not True: issues.append('Original conversation inventory is incomplete')
        if type(data.get('expected_case_count')) is not int or data['expected_case_count']!=len(cases):
            issues.append('Expected original image count has not been reconciled')
        if not data.get('expected_batch_ids'): issues.append('Expected batch inventory is missing')
        if data.get('missing_materials'): issues.append('Historical materials remain missing')
    for row in cases:
        cid=row.get('id')
        if cid in seen: issues.append('Duplicate case: '+str(cid))
        seen.add(cid); batches.add(row.get('batch_id'))
        if row.get('source_kind') not in ('conversation_original','user_original_repository'):
            issues.append(str(cid)+': not an original user image')
        try:
            image=safe_child(root,row['image'])
            if digest(image)!=row.get('sha256'): issues.append(str(cid)+': original bytes changed')
            evaluation=json.loads(safe_child(root,row['evaluation']).read_text())
            if evaluation.get('original_sha256')!=row['sha256']: issues.append(str(cid)+': evaluation hash mismatch')
            for dimension in DIMENSIONS:
                value=evaluation.get('dimensions',{}).get(dimension,{})
                if value.get('status') not in STATUSES: issues.append(str(cid)+': missing dimension '+dimension)
        except (ValueError,KeyError,OSError): issues.append(str(cid)+': missing original/evaluation file')
        if full:
            for field in ('original_ocr','ground_truth'):
                try: safe_child(root,row[field])
                except (ValueError,KeyError,TypeError): issues.append(str(cid)+': missing '+field)
            if row.get('ground_truth_independently_reviewed') is not True:
                issues.append(str(cid)+': independent graph transcription not reviewed')
            if not row.get('batch_id'): issues.append(str(cid)+': batch assignment missing')
    if full and set(data.get('expected_batch_ids') or [])!=batches:
        issues.append('Imported batches do not match original conversation inventory')
    if full and not cases: issues.append('Corpus is empty')
    return issues


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    imp=sub.add_parser('import');imp.add_argument('index');imp.add_argument('--destination',default='tests/real_graph_corpus')
    val=sub.add_parser('validate');val.add_argument('manifest',nargs='?',default='tests/real_graph_corpus/manifest.json');val.add_argument('--full',action='store_true')
    args=parser.parse_args()
    if args.command=='import':
        result=import_index(args.index,args.destination);print(f"Imported inventory now has {len(result['cases'])} originals; completeness remains unconfirmed")
        return 0
    issues=validate_corpus(args.manifest,full=args.full)
    for issue in issues: print(issue)
    return 2 if issues else 0


if __name__=='__main__':raise SystemExit(main())
