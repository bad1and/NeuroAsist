"""Prepare pinned local STT models and 24 public Russian speech excerpts.

Downloads go to .cache/stt-lab. This does not install packages, change Iris
configuration, or upload any audio. Model sources and corpus revision are
recorded in Docs/stt-comparison.md. Run from the repository Python environment.
"""

import concurrent.futures
import json
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / '.cache/stt-lab'
ROOT.mkdir(parents=True, exist_ok=True)
MODELS = ROOT / 'models'
CORPUS = ROOT / 'corpus'
MODELS.mkdir(exist_ok=True)
CORPUS.mkdir(exist_ok=True)

def download(url, destination):
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + '.partial')
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'NeuroAsist-STT-benchmark/1.0'})
            with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            partial.replace(destination)
            print('downloaded', destination.name, destination.stat().st_size, flush=True)
            return destination
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)

def giga():
    revision = '322c3b29492673eb7d0b434bfa9dfb8653e34d02'
    files = ['config.json','v3_vocab.txt','v3_ctc.yaml','v3_rnnt.yaml']
    files += [f'v3_ctc{suffix}.onnx' for suffix in ['', '.int8']]
    files += [f'v3_rnnt_{part}{suffix}.onnx' for part in ['encoder','decoder','joint'] for suffix in ['', '.int8']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda name: download(f'https://huggingface.co/istupakov/gigaam-v3-onnx/resolve/{revision}/{name}', MODELS / 'gigaam-v3' / name), files))
    (MODELS / 'gigaam-v3' / 'revision.txt').write_text(revision, encoding='utf-8')

def sherpa(name):
    folder = MODELS / name
    required = ['model.onnx', 'tokens.txt'] if 't-one' in name else ['encoder.int8.onnx', 'decoder.int8.onnx', 'joiner.int8.onnx', 'tokens.txt']
    if all((folder / file).is_file() for file in required):
        return
    archive = download(f'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{name}.tar.bz2', MODELS / (name + '.tar.bz2'))
    with tarfile.open(archive) as source:
        source.extractall(MODELS, filter='data')
    print('extracted', name, flush=True)

def corpus():
    base='https://datasets-server.huggingface.co/rows?dataset=istupakov%2Frussian_librispeech&config=default&split=test'
    # Spread excerpts across the test set to include different chapters/readers.
    rows=[]
    for offset in [0,200,400,600,800,1000]:
        with urllib.request.urlopen(base+f'&offset={offset}&length=4',timeout=60) as response:
            rows.extend(json.load(response)['rows'])
    manifest=[]
    for record in rows:
        row=record['row']; name=f"ru-{record['row_idx']:04d}.wav"
        url=row['audio'][0]['src']
        revision = 'a519c986bb3342cc8136d3d14e5ad8a4f1e1a2bd'
        if f'/{revision}/' not in url:
            raise RuntimeError('Public corpus revision changed; review before reusing cached audio')
        download(url,CORPUS/name)
        manifest.append({'audio':str((CORPUS/name).resolve()),'reference':row['text'],'tags':['public','human','russian-librispeech'],'source_row':record['row_idx'],'dataset_revision':revision})
    (CORPUS/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('corpus',len(manifest),flush=True)

tasks=[giga,corpus]
for ms in [160,560,1120]:
    name=f'sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-{ms}ms-int8-2026-06-11'
    tasks.append(lambda name=name:sherpa(name))
tasks.append(lambda:sherpa('sherpa-onnx-streaming-t-one-russian-2025-09-08'))
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(task) for task in tasks]
    failures = []
    for future in concurrent.futures.as_completed(futures):
        try:
            future.result()
        except Exception as exc:
            failures.append(exc)
            print('FAILED',repr(exc),flush=True)
if failures:
    raise SystemExit(1)
