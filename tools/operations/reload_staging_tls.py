"""Root-only fixed staging certificate target; uses the reviewed reload logic."""
from pathlib import Path
import os
import sys
from reload_public_tls import reload_public_tls


if __name__ == '__main__':
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise SystemExit('STAGING_TLS_ROOT_LINUX_REQUIRED')
    folder = Path('/www/server/panel/vhost/cert/staging.uiea-thirdhand.com')
    try:
        changed = reload_public_tls([('staging.uiea-thirdhand.com', folder / 'fullchain.pem', folder / 'privkey.pem')])
        print('STAGING_TLS_RELOADED_AND_VERIFIED' if changed else 'STAGING_TLS_UNCHANGED')
    except RuntimeError:
        raise SystemExit('STAGING_TLS_RELOAD_FAILED') from None
