#!/bin/bash

chmod 777 *

echo "net.core.rmem_default=1073741824" >>  /etc/sysctl.d/10-network-security.conf
sync
sync
sync
echo "net.core.rmem_max=1073741824" >>  /etc/sysctl.d/10-network-security.conf
sync
sync
sync
echo "net.core.wmem_default=1073741824" >>  /etc/sysctl.d/10-network-security.conf
sync
sync
sync
echo "net.core.wmem_max=1073741824" >>  /etc/sysctl.d/10-network-security.conf
sync
sync
sync
sysctl -p /etc/sysctl.d/10-network-security.conf
cat /proc/sys/net/core/rmem_default