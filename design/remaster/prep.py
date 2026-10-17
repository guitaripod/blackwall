import json,os,math,collections,pathlib,statistics as st
import sys
root=pathlib.Path(__file__).resolve().parents[2]
board=json.load(open(root/'site'/'board.json'))
suite=board['suites'][board['current']]
KEEP_SPEED=['decode','conc.1','conc.2','conc.4','conc.8','peak','ttft.1000','ttft.8000','ttft.32000','ttft.64000','ttft.120000','decode_at.32000','decode_at.120000']
def slim(m):
    sp={k:v for k,v in (m.get('speed') or {}).items() if k in KEEP_SPEED}
    return {
      'id':m['id'],'name':m['name'],'engine':m.get('engine'),'quant':m.get('quantization'),'spec':m.get('spec'),
      'context':m.get('context'),'index':m.get('index'),'tasks':m.get('tasks'),'speed':sp,
      'wh':(m.get('energy') or {}).get('perCorrect'),
      'lmx':m.get('lmx'),'subs':[{'kind':s['kind'],'value':s['value'],'verified':s.get('verified')} for s in (m.get('submissions') or [])],
      'run':{k:(m.get('run') or {}).get(k) for k in ('id','finished','effort','contended','failedItems','harness')},
      'driver':(m.get('stack') or {}).get('driver'),'build':(m.get('stack') or {}).get('build'),
      'warnings':m.get('warnings') or [],'fingerprint':m.get('fingerprint'),
    }
out={'groups':suite['groups'],'taskLabels':suite['taskLabels'],'taskShort':suite['taskShort'],'taskNotes':suite['taskNotes'],
     'indexTasks':suite['indexTasks'],'efforts':suite['efforts'],'generated':board['generated'],
     'rankings':{e:[slim(m) for m in ms] for e,ms in suite['rankings'].items()},
     'history':[{k:h.get(k) for k in ('run','model','name','effort','finished','index','lo','hi','decode','kind')} for h in board['history']]}
# provisional Bolt (in progress run) from its saved answers
run=sys.argv[1] if len(sys.argv)>1 and sys.argv[1] else None
if run is None:
    (pathlib.Path(__file__).parent/'data.json').write_text(json.dumps(out,separators=(',',':')))
    print('no live run given, wrote the finished board only')
    sys.exit(0)
base=os.path.expanduser('~/.local/share/blackwall/runs/'+str(run))
def ci(vals):
    n=len(vals); m=sum(vals)/n
    sd=(sum((v-m)**2 for v in vals)/max(1,n-1))**.5; h=1.96*sd/math.sqrt(n)
    return m*100,max(0,(m-h)*100),min(100,(m+h)*100)
totals={'supergpqa':521,'math':126,'tools':114,'mrcr':60,'graphwalks':48,'lcb':101}
tasks={}
for t,total in totals.items():
    try: rows=[json.loads(l) for l in open(f'{base}/{t}.jsonl') if l.strip()]
    except FileNotFoundError: continue
    sc=[r['score'] for r in rows if r.get('score') is not None]
    entry={'n':len(rows),'total':total,'tokens':st.mean(r['completion_tokens'] or 0 for r in rows),'latency':st.mean(r['latency'] or 0 for r in rows),
           'truncated':100*sum(1 for r in rows if r.get('finish')=='length')/len(rows)}
    if sc:
        v,lo,hi=ci(sc); entry.update(value=v,lo=lo,hi=hi)
        parts=collections.defaultdict(list)
        for r in rows:
            m=r['meta'] if isinstance(r['meta'],dict) else {}
            key=m.get('bin') or m.get('difficulty') or m.get('category') or m.get('competition')
            if key is not None and r.get('score') is not None: parts[str(key)].append(r['score']*100)
        entry['parts']={k:sum(v)/len(v) for k,v in parts.items()}
    tasks[t]=entry
sp=json.load(open(f'{base}/speed.json'))
def mean(xs): return sum(xs)/len(xs)
speed={'decode':{'value':mean([r['decode_tps'] for r in sp['single'] if r.get('decode_tps')])}}
for c in (1,2,4,8):
    vals=[x['aggregate_tps'] for x in sp['concurrency'] if x['concurrency']==c]
    if vals: speed[f'conc.{c}']={'value':mean(vals)}
for d in (1000,8000,32000,64000,120000):
    vals=[r['ttft_s'] for r in sp['depth'] if r.get('depth')==d and r.get('ttft_s') is not None]
    if vals: speed[f'ttft.{d}']={'value':mean(vals)}
done=sum(1 for t in tasks.values() if 'value' in t)
idx=None
groups=out['groups']
gv=[]
for g,ts in groups.items():
    vals=[tasks[t]['value'] for t in ts if t in tasks and 'value' in tasks[t]]
    if len(vals)==len(ts): gv.append(mean(vals))
out['provisional']=[{'id':'nemotron-3.5-bolt-74b-a9b-24gb-gguf','name':'Nemotron 3.5 Bolt 74B-A9B · llama.cpp · IQ2 24GB · DFlash','engine':'llama.cpp','quant':'IQ2_XXS','spec':'DFlash','context':262144,
  'tasks':tasks,'speed':speed,'groupsDone':len(gv),'partialIndex':(sum(gv)/len(gv) if gv else None),'effort':'max','driver':'615.71.09','run':{'id':run}}]
(pathlib.Path(__file__).parent/'data.json').write_text(json.dumps(out,separators=(',',':')))
print(os.path.getsize('data.json'),'bytes')
print({k:{'n':v['n'],'total':v['total'],'value':round(v.get('value',-1),1)} for k,v in tasks.items()})
print([ (m['id'],round(m['index']['value'],1)) for m in out['rankings']['max']])
print(out['rankings']['max'][1]['tasks']['lcb'].get('parts'), out['rankings']['max'][1]['tasks']['tools'].get('parts'))
