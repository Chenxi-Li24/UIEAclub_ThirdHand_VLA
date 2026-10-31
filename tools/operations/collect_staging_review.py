"""Collect only non-secret C2 acceptance reports; credentials are never included."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

B = Path('/var/backups/thirdhand/access-C2-20261030T125221Z')


def main():
    assert os.geteuid() == 0
    names = ('business-smoke', 'history-export', 'restore-drill', 'postcheck', 'admin-revocation', 'restore-mfa')
    reports = {name: json.loads((B / ('C2-' + name + '.json')).read_text()) for name in names}
    assert all(r['success'] is True for r in reports.values())
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in B.iterdir()
                     if p.name in ('staging-smoke.cjs', 'staging_history_smoke.cjs', 'staging_restore_drill.py', 'staging_postcheck.py', 'staging_admin_smoke.cjs', 'staging_restore_mfa_check.py')}
    stage_size = subprocess.check_output(['runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/psql', '-h', '/run/thirdhand-stage-db', '-p', '55440', '-U', 'postgres', '-d', 'thirdhand_stage', '-Atc', "SELECT pg_database_size(current_database())"]).decode().strip()
    public_cert = subprocess.check_output(['openssl', 'x509', '-in', '/www/server/panel/vhost/cert/staging.uiea-thirdhand.com/fullchain.pem', '-noout', '-dates', '-fingerprint', '-sha256']).decode()
    result = {'collectedAt': datetime.now(timezone.utc).isoformat(), 'origin': 'https://staging.uiea-thirdhand.com',
              'releaseSha256': '73365433069aa612a47b8fa4c1de0abd4dcf635739f1dbbabb8b8c34382788a8',
              'reports': reports, 'operatorScriptSha256': source_hashes, 'databaseBytes': int(stage_size),
              'publicCertificate': public_cert, 'tlsUnchangedAndDirectoryEventPassed': True, 'actualCaRenewalTested': False,
              'browserObserved': {'registrationVerification': True, 'observerAdminDenied': True, 'firstLoginGuide': True,
                                  'modelSlidersAndSequence': True, 'historyQueryAndDownload': True, 'adminTotpAndUserDirectory': True,
                                  'englishLightDefault': True, 'chineseDarkRefreshMemory': True},
              'smtpDeferredByUser': True, 'externalEmailSent': False, 'realSdkCameraOrMotion': False,
              'realTutorialProviderMerged': False, 'showcaseButtonsDeferredByUser': True}
    p = B / 'C2-review-results.json'
    with p.open('x') as output:
        json.dump(result, output, indent=2)
    p.chmod(0o600)
    print('C2_REVIEW_REPORT_READY', p.stat().st_size, flush=True)


if __name__ == '__main__':
    main()
