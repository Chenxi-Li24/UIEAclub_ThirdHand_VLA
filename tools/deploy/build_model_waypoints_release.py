"""Build only the nine reviewed model-waypoint files, never the whole dirty tree."""
import argparse,base64,gzip,hashlib,io,json
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
OLD='/opt/thirdhand-stage/releases/registration-approval-a570d928578cb5bb'
OLD_SHA='4ece5d6ce0577bfce2e734dbe43f6df617484b01868242f9b813a250f171f552'
FILES=('platform/storage/src/model-waypoints.js','services/cloud-api/src/routes/waypoints.js',
       'services/cloud-api/src/server.js','services/cloud-api/src/workspace-pages.js',
       'apps/web/public/js/cloud-workspace.js','apps/web/public/js/workspace-session.js',
       'apps/web/public/js/simulation-controller.js','apps/web/public/js/model-waypoints.js',
       'apps/web/public/css/model-waypoints.css')
ADDED={'platform/storage/src/model-waypoints.js','services/cloud-api/src/routes/waypoints.js',
       'apps/web/public/js/model-waypoints.js','apps/web/public/css/model-waypoints.css'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def build(baseline,destination):
    raw=baseline.read_bytes();assert sha(raw)==OLD_SHA
    before=json.loads(raw);assert len(before['files'])==4630
    contents={name:(REPO/name).read_bytes() for name in FILES}
    assert {name for name in FILES if name not in before['files']}==ADDED
    after=json.loads(raw)
    for name,data in contents.items():after['files'][name]=sha(data)
    manifest=(json.dumps(after,sort_keys=True,indent=2)+'\n').encode();digest=sha(manifest)
    assert {name for name in set(before['files'])|set(after['files']) if before['files'].get(name)!=after['files'].get(name)}==set(FILES)
    new='/opt/thirdhand-stage/releases/'+digest[:16]
    package={'format':1,'oldRelease':OLD,'newRelease':new,'oldManifestSha256':OLD_SHA,'manifestSha256':digest,
             'beforeHashes':{n:before['files'].get(n) for n in FILES},'manifestBase64':base64.b64encode(manifest).decode(),
             'changes':{n:base64.b64encode(data).decode() for n,data in contents.items()}}
    destination.mkdir(parents=True,exist_ok=False)
    (destination/'expected-manifest.json').write_bytes(manifest)
    buffer=io.BytesIO()
    with gzip.GzipFile(fileobj=buffer,mode='wb',filename='',mtime=0) as stream:stream.write(json.dumps(package,sort_keys=True,separators=(',',':')).encode())
    packed=buffer.getvalue();(destination/'cloud.delta.json.gz').write_bytes(packed)
    grant=(REPO/'deploy/public-access/staging/model-waypoint-grants.sql').read_bytes()
    (destination/'model-waypoint-grants.sql').write_bytes(grant)
    report={'format':1,'oldRelease':OLD,'oldManifestSha256':OLD_SHA,'newRelease':new,'manifestSha256':digest,
      'packageSha256':sha(packed),'packageBytes':len(packed),'grantSha256':sha(grant),'filesCount':len(after['files']),
      'addedFiles':sorted(ADDED),'changedFiles':sorted(set(FILES)-ADDED),'deletedFiles':[],
      'preservedFiles':len(before['files'])-len(set(FILES)-ADDED),'sourcePins':{n:sha(d) for n,d in contents.items()},
      'metadataChanged':False,'sdkCommands':0,'newPublicPorts':[],'dependenciesChanged':False}
    (destination/'candidate-summary.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',required=True,type=Path);p.add_argument('--destination',required=True,type=Path);args=p.parse_args()
    print(json.dumps(build(args.baseline,args.destination),sort_keys=True))
