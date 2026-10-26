import hashlib
import json
from pathlib import Path
import pytest
from scripts.graph_corpus import import_index,validate_corpus,DIMENSIONS


def test_partial_corpus_cannot_pass_full_acceptance():
    path=Path('tests/real_graph_corpus/manifest.json')
    assert validate_corpus(path)==[]
    issues=validate_corpus(path,full=True)
    assert any('inventory is incomplete' in x for x in issues)
    assert any('count has not been reconciled' in x for x in issues)


def test_import_preserves_bytes_and_never_infers_ocr_truth_or_completeness(tmp_path):
    source=Path('tests/fixtures/original_ouc_20261021/180506.png')
    image=tmp_path/'source.png';image.write_bytes(source.read_bytes())
    raw=tmp_path/'response.json';raw.write_text('{"text":"actual old response"}')
    index=tmp_path/'index.json';index.write_text(json.dumps({'cases':[{
        'id':'case_1','image':'source.png','original_ocr':'response.json','source_kind':'conversation_original'}]}))
    dest=tmp_path/'corpus';data=import_index(index,dest);row=data['cases'][0]
    assert (dest/row['image']).read_bytes()==source.read_bytes()
    assert (dest/row['original_ocr']).read_bytes()==raw.read_bytes()
    assert data['enumeration_complete'] is False and row['ground_truth'] is None
    evaluation=json.loads((dest/row['evaluation']).read_text())
    assert set(evaluation['dimensions'])==set(DIMENSIONS)
    assert all(v['status']=='not_evaluated' for v in evaluation['dimensions'].values())


def test_generated_images_cannot_be_imported_as_historical_originals(tmp_path):
    index=tmp_path/'index.json';index.write_text(json.dumps({'cases':[{
        'id':'fake','image':'fake.png','source_kind':'generated'}]}))
    with pytest.raises(ValueError,match='actual user originals'):import_index(index,tmp_path/'out')


def test_original_hash_mismatch_rejected_before_copy(tmp_path):
    image=tmp_path/'source.png';image.write_bytes(b'not-the-original')
    index=tmp_path/'index.json';index.write_text(json.dumps({'cases':[{
        'id':'case1','image':'source.png','source_kind':'conversation_original','sha256':'0'*64}]}))
    with pytest.raises(ValueError,match='hash mismatch'):import_index(index,tmp_path/'out')
    assert not (tmp_path/'out/cases/case1').exists()
