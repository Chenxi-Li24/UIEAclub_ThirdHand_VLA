"""Build the fixed C7 runtime delta from normalized Git index bytes, not a dirty tree."""
import argparse,base64,gzip,hashlib,io,json,re,subprocess
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
OLD='/opt/thirdhand-stage/releases/7c7f4b5f3792288e'
OLD_SHA='7c7f4b5f3792288ec42d98ddbd25151ae192a766f8a7f16fd996afe6ba35f63c'
CHANGED={
 'apps/web/public/js/'+n+'.js' for n in ('account-settings','camera-view','cloud-workspace','i18n-cloud-catalog','onboarding','preferences','robot-viewer','workspace-session')
}|{'platform/identity/src/preferences.js'}|{
 'services/cloud-api/src/'+n+'.js' for n in ('asset-paths','auth-pages','server','workspace-pages')
}
ADDED={'apps/web/public/classic.html','apps/web/public/css/classic-source.css','apps/web/public/css/workspace-layouts.css',
 'platform/storage/migrations/011-workspace-layout.sql','services/cloud-api/src/workspace-bootstrap.js','configs/web/classic-source.json'}|{
 'apps/web/public/js/'+n+'.js' for n in ('classic-shell','model-resources','workspace-startup')
}|{'apps/web/public/js/lib/'+n for n in ('loaders/GLTFLoader.js','utils/BufferGeometryUtils.js','meshopt_decoder.module.js',
 'meshoptimizer-0.22.0.LICENSE.md','three-r163.LICENSE.txt','WEB-MODEL-DEPENDENCIES.md')}|{
 'assets/robot/startouch-v3/web/'+n for n in ('robot-visuals.glb','robot-visuals.glb.gz','build-report.json','README.md')
}
FILES=CHANGED|ADDED

def sha(raw):return hashlib.sha256(raw).hexdigest()

def index_bytes(name):
    raw=subprocess.run(['git','show',':'+name],cwd=REPO,check=True,capture_output=True).stdout
    if raw.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
        pointer=re.fullmatch(rb'version https://git-lfs.github.com/spec/v1\noid sha256:([a-f0-9]{64})\nsize ([0-9]+)\n',raw)
        assert pointer,'invalid LFS pointer'
        raw=(REPO/name).read_bytes()
        assert sha(raw)==pointer[1].decode() and len(raw)==int(pointer[2]),'restore the pinned LFS payload'
    return raw

def build(baseline,destination,read_source=index_bytes):
    raw=baseline.read_bytes();assert sha(raw)==OLD_SHA,'server baseline changed'
    before=json.loads(raw);assert len(before['files'])==4634
    assert CHANGED<=set(before['files']) and not ADDED&set(before['files'])
    contents={name:read_source(name) for name in sorted(FILES)}
    after=json.loads(raw)
    after['files'].update({n:sha(data) for n,data in contents.items()})
    assert {n for n in set(before['files'])|set(after['files']) if before['files'].get(n)!=after['files'].get(n)}==FILES
    manifest=(json.dumps(after,sort_keys=True,indent=2)+'\n').encode();digest=sha(manifest)
    new='/opt/thirdhand-stage/releases/'+digest[:16]
    package={'format':1,'oldRelease':OLD,'newRelease':new,'oldManifestSha256':OLD_SHA,'manifestSha256':digest,
      'beforeHashes':{n:before['files'].get(n) for n in sorted(FILES)},'manifestBase64':base64.b64encode(manifest).decode(),
      'changes':{n:base64.b64encode(data).decode() for n,data in contents.items()}}
    buffer=io.BytesIO()
    with gzip.GzipFile(fileobj=buffer,mode='wb',filename='',mtime=0) as stream:
        stream.write(json.dumps(package,sort_keys=True,separators=(',',':')).encode())
    packed=buffer.getvalue();assert len(packed)<=8*1024*1024
    destination.mkdir(parents=True,exist_ok=False)
    (destination/'expected-manifest.json').write_bytes(manifest)
    (destination/'cloud.delta.json.gz').write_bytes(packed)
    report={'format':1,'oldRelease':OLD,'oldManifestSha256':OLD_SHA,'newRelease':new,'manifestSha256':digest,
      'packageSha256':sha(packed),'packageBytes':len(packed),'filesCount':len(after['files']),
      'sourcePins':{n:sha(data) for n,data in contents.items()},'migrationSha256':sha(contents['platform/storage/migrations/011-workspace-layout.sql']),
      'addedFiles':sorted(ADDED),'changedFiles':sorted(CHANGED),'deletedFiles':[],
      'preservedFiles':len(before['files'])-len(CHANGED),'metadataChanged':False,
      'sdkCommands':0,'newPublicPorts':[],'productionDependenciesChanged':False}
    (destination/'candidate-summary.json').write_bytes((json.dumps(report,sort_keys=True,indent=2)+'\n').encode())
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',required=True,type=Path);p.add_argument('--destination',required=True,type=Path);a=p.parse_args()
    print(json.dumps(build(a.baseline,a.destination),sort_keys=True))
